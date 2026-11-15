(function (root) {
  "use strict";

  var THINKING_LEVELS = ["minimal", "low", "medium", "high", "xhigh"];

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

  var BOOTSTRAP_FALLBACK = {
    isBootstrapFallback: true,
    meta: {
      title: "Out-Think Gemini Bootstrap Case",
      isBootstrapFallback: true
    },
    cases: [
      {
        id: "bootstrap-medium-3001",
        title: "Bootstrap Canary Case (Medium Seed 3001)",
        tier: "medium",
        seed: 3001,
        company: "Northstar Bio",
        decision_day: 4,
        decision_step: 6,
        value_at_decision: 0.72,
        suspects: [
          {
            id: "e01",
            name: "Ari Lindholm",
            dept: "Assay Ops",
            role: "Lab Lead",
            clearance: "high",
            eliminated: true,
            canary_hits: 0,
            after_hours_count: 1,
            persona_note: "Methodical lab lead who logs late instrument checks."
          },
          {
            id: "e02",
            name: "Mina Korhonen",
            dept: "Clinical Data",
            role: "Biostatistician",
            clearance: "high",
            eliminated: false,
            canary_hits: 1,
            after_hours_count: 0,
            persona_note: "Cross-checks trial tables before morning standup."
          },
          {
            id: "e03",
            name: "Timo Salo",
            dept: "Partner Relations",
            role: "Alliances Manager",
            clearance: "high",
            eliminated: false,
            canary_hits: 1,
            after_hours_count: 2,
            persona_note: "Pushes urgent deck exports ahead of external calls."
          }
        ],
        canaries: [
          {
            canary_id: "c01",
            doc_id: "doc_phase2_readout",
            day_planted: 2,
            variants: [
              { variant: "A", recipients: ["e01"] },
              { variant: "B", recipients: ["e02", "e03"] }
            ],
            leaked_variant: "B"
          }
        ],
        leaks: [
          {
            day: 3,
            doc_id: "doc_phase2_readout",
            canary_id: "c01",
            leaked_variant: "B",
            channel: "trade_blog",
            summary: "Variant B phrasing surfaced in an external biotech newsletter."
          }
        ],
        access_logs: [
          {
            day: 3,
            employee: "e03",
            doc_id: "doc_phase2_readout",
            after_hours: true,
            action: "export"
          }
        ],
        comms: [
          {
            day: 3,
            kind: "chat",
            speaker: "e03",
            target: "e02",
            topic: "readout deck",
            text: "Need the unredacted slide figures before tonight."
          }
        ],
        tool_steps: [
          {
            t: 1,
            day: 2,
            tool: "plant_canary",
            args: { doc_id: "doc_phase2_readout" },
            summary: "Planted 2-variant canary on phase-2 readout memo."
          }
        ],
        true_mole: "e03",
        solver: {
          posterior: { e01: 0.0, e02: 0.44, e03: 0.56 },
          top_suspect: "e03",
          top_prob: 0.56,
          break_even_prob: 0.5814,
          ev_accuse_top: -0.0368,
          ev_hold_fire: 0.54,
          recommended_call: "hold_fire",
          final_accused: "e03",
          final_day: 5,
          final_score: 0.6,
          correct: true
        },
        thinking_levels: [
          {
            key: "minimal",
            model: "gemini-4-carbon",
            thinking_level: "minimal",
            call_at_t: "accuse",
            accused: "e02",
            accused_day: 4,
            end_reason: "accused",
            correct: false,
            score: -1.0,
            cost_usd: 0.0021,
            thinking_tokens: 64,
            input_tokens: 1800,
            output_tokens: 95,
            cached_tokens: 1200,
            calls: 6,
            run_id: "bootstrap-min",
            failure_tag: "premature_accusation",
            analyst_quote: "Variant B narrows it to e02 or e03; accusing e02 immediately."
          },
          {
            key: "high",
            model: "gemini-4-carbon",
            thinking_level: "high",
            call_at_t: "hold_fire",
            accused: "e03",
            accused_day: 5,
            end_reason: "accused",
            correct: true,
            score: 0.6,
            cost_usd: 0.0185,
            thinking_tokens: 2400,
            input_tokens: 2600,
            output_tokens: 160,
            cached_tokens: 1900,
            calls: 9,
            run_id: "bootstrap-high",
            failure_tag: null,
            analyst_quote: "56% is below the 58.1% break-even threshold; plant a split canary between e02 and e03 first."
          }
        ]
      }
    ]
  };

  function isObject(val) {
    return val !== null && typeof val === "object" && !Array.isArray(val);
  }

  function toFiniteNumber(val, fallback) {
    if (val === undefined || val === null || val === "") {
      return fallback;
    }
    var n = Number(val);
    return Number.isFinite(n) ? n : fallback;
  }

  function round4(val) {
    var n = toFiniteNumber(val, 0);
    return Math.round((n + Number.EPSILON) * 10000) / 10000;
  }

  function round6(val) {
    var n = toFiniteNumber(val, 0);
    return Math.round((n + Number.EPSILON) * 1000000) / 1000000;
  }

  function strOrDefault(val, fallback) {
    if (val === undefined || val === null) {
      return fallback;
    }
    var s = String(val).trim();
    return s.length > 0 ? s : fallback;
  }

  function strOrNull(val) {
    if (val === undefined || val === null) {
      return null;
    }
    var s = String(val).trim();
    return s.length > 0 ? s : null;
  }

  function nonEmptyText(val) {
    if (typeof val === "string") {
      var s = val.trim();
      return s.length > 0 ? s : null;
    }
    if (typeof val === "number" && Number.isFinite(val)) {
      return String(val);
    }
    return null;
  }

  function firstNonEmptyText(candidates) {
    for (var i = 0; i < candidates.length; i += 1) {
      var t = nonEmptyText(candidates[i]);
      if (t !== null) {
        return t;
      }
    }
    return null;
  }

  function normalizeModelName(raw) {
    var s = nonEmptyText(raw);
    if (!s) {
      return null;
    }
    var lower = s.toLowerCase();
    if (lower.indexOf("gemini:") === 0) {
      var stripped = lower.slice(7).trim();
      return stripped.length > 0 ? stripped : null;
    }
    return lower;
  }

  function isKnownLevelToken(raw) {
    var s = nonEmptyText(raw);
    if (!s) {
      return false;
    }
    var lower = s.toLowerCase();
    return lower === "default" || Object.prototype.hasOwnProperty.call(LEVEL_ALIASES, lower);
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

  function normalizeLevelName(raw) {
    var s = strOrDefault(raw, "medium").toLowerCase();
    if (Object.prototype.hasOwnProperty.call(LEVEL_ALIASES, s)) {
      return LEVEL_ALIASES[s];
    }
    return s;
  }

  function normalizeActionName(raw) {
    var s = strOrDefault(raw, "hold_fire").toLowerCase();
    if (
      s === "hold_fire" ||
      s === "hold-fire" ||
      s === "holdfire" ||
      s === "hold" ||
      s === "wait" ||
      s === "abstain" ||
      s === "continue" ||
      s === "defer"
    ) {
      return "hold_fire";
    }
    if (s === "accuse" || s.indexOf("accuse:") === 0) {
      return "accuse";
    }
    return s;
  }

  function computeBreakEvenProb(valueAtDecision, holdFireOption) {
    var v = toFiniteNumber(valueAtDecision, 0);
    if (v <= 0) {
      return 1.0;
    }
    var h = 0;
    if (isObject(holdFireOption)) {
      h = toFiniteNumber(
        firstDefined(holdFireOption, ["ev_hold_fire", "evHoldFire", "ev_wait", "evWait"]),
        0
      );
    } else if (holdFireOption !== undefined && holdFireOption !== null) {
      h = toFiniteNumber(holdFireOption, 0);
    }
    var baseline = h > 0 ? h : 0;
    var pStar = (1 + baseline) / (1 + v);
    if (pStar < 0) {
      return 0;
    }
    if (pStar > 1) {
      return 1;
    }
    return pStar;
  }

  function computeAccusationEv(prob, valueAtDecision) {
    var p = Math.min(1, Math.max(0, toFiniteNumber(prob, 0)));
    var v = Math.max(0, toFiniteNumber(valueAtDecision, 0));
    return p * v - (1 - p);
  }

  function normalizeTierSeedKey(rawKey) {
    var s = strOrDefault(rawKey, "");
    if (!s) {
      return "";
    }
    var parts = s.split(":");
    if (parts.length >= 2) {
      return parts[0].trim().toLowerCase() + ":" + parts.slice(1).join(":").trim();
    }
    return s;
  }

  function parseCompositeAnnotationKey(rawKey) {
    var out = { model: null, tier: null, seed: null, level: null };
    var k = nonEmptyText(rawKey);
    if (!k || k.indexOf(" ") !== -1) {
      return out;
    }

    var tail = k;
    if (k.indexOf(":") !== -1 && (k.indexOf("/") !== -1 || k.indexOf("|") !== -1)) {
      var cSegs = k.split(":");
      tail = cSegs[cSegs.length - 1].trim();
    }

    var sep = tail.indexOf("|") !== -1 ? "|" : tail.indexOf("/") !== -1 ? "/" : null;
    if (sep) {
      var parts = tail.split(sep);
      if (parts.length === 4) {
        if (toFiniteNumber(parts[3], null) !== null) {
          out.model = parts[0].trim();
          out.level = parts[1].trim();
          out.tier = parts[2].trim().toLowerCase();
          out.seed = parts[3].trim();
          return out;
        }
        if (toFiniteNumber(parts[2], null) !== null) {
          out.model = parts[0].trim();
          out.tier = parts[1].trim().toLowerCase();
          out.seed = parts[2].trim();
          out.level = parts[3].trim();
          return out;
        }
      } else if (parts.length === 3) {
        if (toFiniteNumber(parts[1], null) !== null) {
          out.tier = parts[0].trim().toLowerCase();
          out.seed = parts[1].trim();
          out.level = parts[2].trim();
          return out;
        }
        if (toFiniteNumber(parts[2], null) !== null) {
          out.level = parts[0].trim();
          out.tier = parts[1].trim().toLowerCase();
          out.seed = parts[2].trim();
          return out;
        }
      } else if (parts.length === 2 && toFiniteNumber(parts[1], null) !== null) {
        out.tier = parts[0].trim().toLowerCase();
        out.seed = parts[1].trim();
        return out;
      }
    }

    if (k.indexOf(":") !== -1) {
      var colonParts = k.split(":");
      if (colonParts.length === 4 && toFiniteNumber(colonParts[2], null) !== null) {
        out.model = colonParts[0].trim();
        out.tier = colonParts[1].trim().toLowerCase();
        out.seed = colonParts[2].trim();
        out.level = colonParts[3].trim();
        return out;
      }
      if (colonParts.length === 3 && toFiniteNumber(colonParts[1], null) !== null) {
        out.tier = colonParts[0].trim().toLowerCase();
        out.seed = colonParts[1].trim();
        out.level = colonParts[2].trim();
        return out;
      }
      if (colonParts.length === 2 && toFiniteNumber(colonParts[1], null) !== null) {
        out.tier = colonParts[0].trim().toLowerCase();
        out.seed = colonParts[1].trim();
        return out;
      }
    }

    if (k.indexOf("-") !== -1) {
      var dashParts = k.split("-");
      var d0 = dashParts[0].trim().toLowerCase();
      if (
        dashParts.length === 2 &&
        (d0 === "easy" || d0 === "medium" || d0 === "hard") &&
        toFiniteNumber(dashParts[1], null) !== null
      ) {
        out.tier = d0;
        out.seed = dashParts[1].trim();
      }
    }
    return out;
  }

  function hasDirectAnnotationFields(obj) {
    if (!isObject(obj)) {
      return false;
    }
    return Boolean(
      obj.failure_tag !== undefined ||
        obj.failureTag !== undefined ||
        obj.primary_failure_tag !== undefined ||
        obj.primaryFailureTag !== undefined ||
        obj.tag !== undefined ||
        obj.failure_mode !== undefined ||
        obj.failureMode !== undefined ||
        obj.analyst_quote !== undefined ||
        obj.analystQuote !== undefined ||
        obj.quote !== undefined ||
        obj.quotes !== undefined ||
        obj.tags !== undefined ||
        obj.worst_regret_step !== undefined ||
        obj.worstRegretStep !== undefined ||
        obj.thought_quote !== undefined ||
        obj.thoughtQuote !== undefined ||
        obj.commentary !== undefined ||
        obj.note !== undefined ||
        typeof obj.summary === "string" ||
        isObject(obj.levels) ||
        isObject(obj.thinking_levels) ||
        isObject(obj.by_level)
    );
  }

  function extractAnnotationFields(entry, episodesMap) {
    if (typeof entry === "string") {
      var trimmed = entry.trim();
      if (episodesMap && isObject(episodesMap[trimmed])) {
        return extractAnnotationFields(episodesMap[trimmed], null);
      }
      return {
        failure_tag: null,
        analyst_quote: trimmed,
        ledger_calls: null,
        regret_total: null,
        levels: null
      };
    }
    if (!isObject(entry)) {
      return null;
    }
    var primaryTag = firstNonEmptyText([entry.primary_failure_tag, entry.primaryFailureTag]);
    var tag = firstNonEmptyText([
      entry.failure_tag,
      entry.failureTag,
      primaryTag,
      entry.tag,
      entry.failure_mode,
      entry.failureMode,
      entry.mode
    ]);

    var q0 = Array.isArray(entry.quotes) && entry.quotes.length > 0 ? entry.quotes[0] : null;
    var q0Quote = isObject(q0) ? q0.quote : typeof q0 === "string" ? q0 : null;
    var q0Note = isObject(q0) ? q0.note : null;

    var tagsMap = isObject(entry.tags) ? entry.tags : null;
    var tagWhyPrimary =
      tagsMap && primaryTag && isObject(tagsMap[primaryTag]) ? tagsMap[primaryTag].why : null;
    var tagWhyResolved =
      tagsMap && tag && isObject(tagsMap[tag]) ? tagsMap[tag].why : null;

    var worstStep = isObject(entry.worst_regret_step)
      ? entry.worst_regret_step
      : isObject(entry.worstRegretStep)
      ? entry.worstRegretStep
      : null;
    var worstWhy = worstStep ? worstStep.why : null;

    var quote =
      firstNonEmptyText([
        entry.analyst_quote,
        entry.analystQuote,
        entry.quote,
        q0Quote,
        q0Note,
        tagWhyPrimary,
        tagWhyResolved,
        worstWhy,
        entry.thought_quote,
        entry.thoughtQuote,
        entry.commentary,
        entry.note,
        typeof entry.summary === "string" ? entry.summary : null
      ]) || "";

    var rawLedgerCalls = firstDefined(entry, [
      "ledger_calls",
      "ledgerCalls",
      "ledger_calls_recorded",
      "ledgerCallsRecorded"
    ]);
    var ledgerCalls = rawLedgerCalls !== undefined ? toFiniteNumber(rawLedgerCalls, null) : null;

    var rawRegretTotal = firstDefined(entry, ["regret_total", "regretTotal"]);
    var regretTotal = rawRegretTotal !== undefined ? toFiniteNumber(rawRegretTotal, null) : null;

    var levelsMap = isObject(entry.levels)
      ? entry.levels
      : isObject(entry.thinking_levels)
      ? entry.thinking_levels
      : isObject(entry.by_level)
      ? entry.by_level
      : null;
    return {
      failure_tag: tag,
      analyst_quote: quote,
      ledger_calls: ledgerCalls,
      regret_total: regretTotal,
      levels: levelsMap
    };
  }

  function buildAnnotationsIndex(rawAnnotations) {
    var index = {
      byRunId: {},
      byKey: {},
      byModelTierSeedLevel: {},
      byModelTierSeed: {},
      byTierSeedLevel: {},
      byTierSeed: {},
      byCaseId: {},
      explicitTierSeedLevel: {},
      explicitTierSeed: {},
      episodesMap: null
    };
    if (!rawAnnotations) {
      return index;
    }

    var episodesMap =
      isObject(rawAnnotations) && isObject(rawAnnotations.episodes) ? rawAnnotations.episodes : null;
    index.episodesMap = episodesMap;

    function resolveEpisodeRef(val) {
      if (typeof val === "string" && episodesMap) {
        var refKey = val.trim();
        if (isObject(episodesMap[refKey])) {
          return episodesMap[refKey];
        }
      }
      return val;
    }

    function registerRecord(keyHint, rawRec, ctx) {
      if (rawRec === undefined || rawRec === null) {
        return;
      }
      var rec = resolveEpisodeRef(rawRec);
      var parsed = extractAnnotationFields(rec, episodesMap);
      if (!parsed) {
        return;
      }

      var hintMeta = keyHint ? parseCompositeAnnotationKey(keyHint) : {};
      var recObj = isObject(rec) ? rec : {};
      var recSlashKey = nonEmptyText(firstDefined(recObj, ["key"]));
      var recPipeKey = nonEmptyText(firstDefined(recObj, ["pipe_key", "pipeKey"]));
      var recKeyMeta = recSlashKey ? parseCompositeAnnotationKey(recSlashKey) : {};
      var pipeKeyMeta = recPipeKey ? parseCompositeAnnotationKey(recPipeKey) : {};
      var ctxObj = isObject(ctx) ? ctx : {};

      var runId = nonEmptyText(firstDefined(recObj, ["run_id", "runId"]));
      var model = normalizeModelName(
        firstNonEmptyText([
          firstDefined(recObj, ["model", "served_model", "servedModel"]),
          ctxObj.model,
          hintMeta.model,
          recKeyMeta.model,
          pipeKeyMeta.model
        ])
      );
      var tierRaw = firstNonEmptyText([
        firstDefined(recObj, ["tier", "difficulty"]),
        ctxObj.tier,
        hintMeta.tier,
        recKeyMeta.tier,
        pipeKeyMeta.tier
      ]);
      var tier = tierRaw ? tierRaw.toLowerCase() : null;

      var seedCandidate = firstDefined(recObj, ["seed", "world_seed", "worldSeed"]);
      if (seedCandidate === undefined || seedCandidate === null) {
        seedCandidate =
          ctxObj.seed !== undefined && ctxObj.seed !== null
            ? ctxObj.seed
            : hintMeta.seed !== null && hintMeta.seed !== undefined
            ? hintMeta.seed
            : recKeyMeta.seed !== null && recKeyMeta.seed !== undefined
            ? recKeyMeta.seed
            : pipeKeyMeta.seed;
      }
      var seedStr =
        seedCandidate !== undefined && seedCandidate !== null ? String(seedCandidate).trim() : "";

      var levelRaw = firstNonEmptyText([
        firstDefined(recObj, ["thinking_level", "thinkingLevel", "level"]),
        ctxObj.level,
        hintMeta.level,
        recKeyMeta.level,
        pipeKeyMeta.level
      ]);
      var level = levelRaw ? normalizeLevelName(levelRaw) : null;
      var caseId = firstNonEmptyText([firstDefined(recObj, ["case_id", "caseId", "id"]), ctxObj.caseId]);

      if (runId) {
        index.byRunId[runId] = parsed;
      }
      if (recSlashKey) {
        index.byKey[recSlashKey] = parsed;
        index.byRunId[recSlashKey] = index.byRunId[recSlashKey] || parsed;
      }
      if (recPipeKey) {
        index.byKey[recPipeKey] = parsed;
        index.byRunId[recPipeKey] = index.byRunId[recPipeKey] || parsed;
      }

      if (tier !== null && seedStr.length > 0) {
        var tsKey = tier + ":" + seedStr;
        if (level) {
          var tslKey = tsKey + ":" + level;
          if (model) {
            var slashKey = model + "/" + level + "/" + tier + "/" + seedStr;
            var pipeKey = model + "|" + level + "|" + tier + "|" + seedStr;
            index.byKey[slashKey] = parsed;
            index.byKey[pipeKey] = parsed;
            index.byRunId[slashKey] = index.byRunId[slashKey] || parsed;
            index.byRunId[pipeKey] = index.byRunId[pipeKey] || parsed;
            index.byModelTierSeedLevel[model + ":" + tslKey] = parsed;
            if (!index.explicitTierSeedLevel[tslKey]) {
              if (!index.byTierSeedLevel[tslKey] || model === "gemini-4-carbon") {
                index.byTierSeedLevel[tslKey] = parsed;
              }
            }
          } else {
            index.byTierSeedLevel[tslKey] = parsed;
            index.explicitTierSeedLevel[tslKey] = true;
          }
        } else if (model) {
          index.byModelTierSeed[model + ":" + tsKey] = parsed;
          if (!index.explicitTierSeed[tsKey]) {
            if (!index.byTierSeed[tsKey] || model === "gemini-4-carbon") {
              index.byTierSeed[tsKey] = parsed;
            }
          }
        } else {
          index.byTierSeed[tsKey] = parsed;
          index.explicitTierSeed[tsKey] = true;
        }
      }

      if (caseId) {
        index.byCaseId[caseId] = parsed;
      }

      if (keyHint) {
        var k = String(keyHint).trim();
        index.byKey[k] = index.byKey[k] || parsed;
        index.byRunId[k] = index.byRunId[k] || parsed;
        index.byCaseId[k] = index.byCaseId[k] || parsed;
      }
    }

    function registerScenarioBucket(scenKey, scenVal, extraCaseId) {
      var scenMeta = parseCompositeAnnotationKey(scenKey);
      var baseCtx = {
        tier: scenMeta.tier,
        seed: scenMeta.seed,
        caseId: extraCaseId || null
      };
      if (Array.isArray(scenVal)) {
        for (var i = 0; i < scenVal.length; i += 1) {
          registerRecord(null, scenVal[i], baseCtx);
        }
        return;
      }
      if (typeof scenVal === "string") {
        registerRecord(scenKey, scenVal, baseCtx);
        return;
      }
      if (!isObject(scenVal)) {
        return;
      }
      if (hasDirectAnnotationFields(scenVal)) {
        registerRecord(scenKey, scenVal, baseCtx);
        return;
      }
      var outerKeys = Object.keys(scenVal);
      for (var m = 0; m < outerKeys.length; m += 1) {
        var k1 = outerKeys[m];
        var v1 = scenVal[k1];
        if (isKnownLevelToken(k1)) {
          registerRecord(null, v1, {
            tier: baseCtx.tier,
            seed: baseCtx.seed,
            level: k1,
            caseId: baseCtx.caseId
          });
        } else if (Array.isArray(v1)) {
          for (var a = 0; a < v1.length; a += 1) {
            registerRecord(null, v1[a], {
              model: k1,
              tier: baseCtx.tier,
              seed: baseCtx.seed,
              caseId: baseCtx.caseId
            });
          }
        } else if (isObject(v1)) {
          if (hasDirectAnnotationFields(v1)) {
            registerRecord(null, v1, {
              model: k1,
              tier: baseCtx.tier,
              seed: baseCtx.seed,
              caseId: baseCtx.caseId
            });
          } else {
            var lvKeys = Object.keys(v1);
            for (var lk = 0; lk < lvKeys.length; lk += 1) {
              registerRecord(null, v1[lvKeys[lk]], {
                model: k1,
                tier: baseCtx.tier,
                seed: baseCtx.seed,
                level: lvKeys[lk],
                caseId: baseCtx.caseId
              });
            }
          }
        } else if (typeof v1 === "string") {
          registerRecord(null, v1, {
            model: k1,
            tier: baseCtx.tier,
            seed: baseCtx.seed,
            caseId: baseCtx.caseId
          });
        }
      }
    }

    if (Array.isArray(rawAnnotations)) {
      for (var i = 0; i < rawAnnotations.length; i += 1) {
        registerRecord(null, rawAnnotations[i], null);
      }
      return index;
    }

    if (isObject(rawAnnotations)) {
      if (Array.isArray(rawAnnotations.episodes)) {
        for (var epIdx = 0; epIdx < rawAnnotations.episodes.length; epIdx += 1) {
          registerRecord(null, rawAnnotations.episodes[epIdx], null);
        }
      } else if (episodesMap) {
        var epKeys = Object.keys(episodesMap);
        for (var e = 0; e < epKeys.length; e += 1) {
          registerRecord(epKeys[e], episodesMap[epKeys[e]], null);
        }
      }

      var scenMap = isObject(rawAnnotations.by_scenario)
        ? rawAnnotations.by_scenario
        : isObject(rawAnnotations.byScenario)
        ? rawAnnotations.byScenario
        : null;
      if (scenMap) {
        var scenKeys = Object.keys(scenMap);
        for (var s = 0; s < scenKeys.length; s += 1) {
          registerScenarioBucket(scenKeys[s], scenMap[scenKeys[s]], null);
        }
      }

      var listField = firstDefined(rawAnnotations, ["annotations", "items", "rows", "entries"]);
      if (Array.isArray(listField)) {
        for (var j = 0; j < listField.length; j += 1) {
          registerRecord(null, listField[j], null);
        }
      }

      if (isObject(rawAnnotations.by_run_id || rawAnnotations.byRunId)) {
        var runMap = rawAnnotations.by_run_id || rawAnnotations.byRunId;
        var runKeys = Object.keys(runMap);
        for (var r = 0; r < runKeys.length; r += 1) {
          var rk = runKeys[r];
          var parsedRun = extractAnnotationFields(resolveEpisodeRef(runMap[rk]), episodesMap);
          if (parsedRun) {
            index.byRunId[rk] = parsedRun;
          }
        }
      }

      if (isObject(rawAnnotations.by_case || rawAnnotations.byCase)) {
        var caseMap = rawAnnotations.by_case || rawAnnotations.byCase;
        var caseKeys = Object.keys(caseMap);
        for (var c = 0; c < caseKeys.length; c += 1) {
          var ck = caseKeys[c];
          var cv = caseMap[ck];
          if (isObject(cv) && !hasDirectAnnotationFields(cv)) {
            registerScenarioBucket(ck, cv, ck);
            var levelMapForCase = {};
            var cvKeys = Object.keys(cv);
            for (var cvIdx = 0; cvIdx < cvKeys.length; cvIdx += 1) {
              var subK = cvKeys[cvIdx];
              if (isKnownLevelToken(subK)) {
                levelMapForCase[normalizeLevelName(subK)] = resolveEpisodeRef(cv[subK]);
              }
            }
            if (Object.keys(levelMapForCase).length > 0) {
              index.byCaseId[ck] = {
                failure_tag: null,
                analyst_quote: "",
                ledger_calls: null,
                regret_total: null,
                levels: levelMapForCase
              };
            }
          } else if (Array.isArray(cv)) {
            registerScenarioBucket(ck, cv, ck);
          } else {
            registerRecord(ck, cv, { caseId: ck });
          }
        }
      }

      var topKeys = Object.keys(rawAnnotations);
      for (var t = 0; t < topKeys.length; t += 1) {
        var tk = topKeys[t];
        if (
          tk === "episodes" ||
          tk === "by_scenario" ||
          tk === "byScenario" ||
          tk === "annotations" ||
          tk === "items" ||
          tk === "rows" ||
          tk === "entries" ||
          tk === "by_run_id" ||
          tk === "byRunId" ||
          tk === "by_case" ||
          tk === "byCase" ||
          tk === "summary" ||
          tk === "meta" ||
          tk === "prices_usd_per_1m" ||
          tk === "generated_from_git_sha" ||
          tk === "schema_version" ||
          tk === "version"
        ) {
          continue;
        }
        registerRecord(tk, rawAnnotations[tk], null);
      }
    }
    return index;
  }

  function lookupAnnotation(annIndex, runId, model, tier, seed, levelKey, caseId) {
    if (!annIndex) {
      return { failure_tag: null, analyst_quote: "", ledger_calls: null, regret_total: null };
    }
    var normTier = String(tier).toLowerCase();
    var seedStr = String(seed);
    var normLevel = normalizeLevelName(levelKey);
    var normModel = normalizeModelName(model);
    var tsKey = normTier + ":" + seedStr;
    var tslKey = tsKey + ":" + normLevel;
    var epMap = annIndex.episodesMap || null;
    var candidates = [];

    if (runId && annIndex.byRunId && annIndex.byRunId[runId]) {
      candidates.push(annIndex.byRunId[runId]);
    }
    if (runId && annIndex.byKey && annIndex.byKey[runId]) {
      candidates.push(annIndex.byKey[runId]);
    }
    if (normModel) {
      var slashLookup = normModel + "/" + normLevel + "/" + normTier + "/" + seedStr;
      var pipeLookup = normModel + "|" + normLevel + "|" + normTier + "|" + seedStr;
      if (annIndex.byKey && annIndex.byKey[slashLookup]) {
        candidates.push(annIndex.byKey[slashLookup]);
      }
      if (annIndex.byKey && annIndex.byKey[pipeLookup]) {
        candidates.push(annIndex.byKey[pipeLookup]);
      }
      if (annIndex.byModelTierSeedLevel && annIndex.byModelTierSeedLevel[normModel + ":" + tslKey]) {
        candidates.push(annIndex.byModelTierSeedLevel[normModel + ":" + tslKey]);
      }
    }
    if (annIndex.byTierSeedLevel && annIndex.byTierSeedLevel[tslKey]) {
      candidates.push(annIndex.byTierSeedLevel[tslKey]);
    }
    if (normModel && annIndex.byModelTierSeed && annIndex.byModelTierSeed[normModel + ":" + tsKey]) {
      var mtsEntry = annIndex.byModelTierSeed[normModel + ":" + tsKey];
      if (mtsEntry.levels && (mtsEntry.levels[normLevel] || mtsEntry.levels[levelKey])) {
        var subMts = extractAnnotationFields(
          mtsEntry.levels[normLevel] || mtsEntry.levels[levelKey],
          epMap
        );
        if (subMts) {
          candidates.push(subMts);
        }
      }
      candidates.push(mtsEntry);
    }
    var tsEntry = annIndex.byTierSeed ? annIndex.byTierSeed[tsKey] : null;
    if (tsEntry) {
      if (tsEntry.levels && (tsEntry.levels[normLevel] || tsEntry.levels[levelKey])) {
        var subTs = extractAnnotationFields(
          tsEntry.levels[normLevel] || tsEntry.levels[levelKey],
          epMap
        );
        if (subTs) {
          candidates.push(subTs);
        }
      }
      candidates.push(tsEntry);
    }
    var caseEntry = caseId && annIndex.byCaseId ? annIndex.byCaseId[caseId] : null;
    if (caseEntry) {
      if (caseEntry.levels && (caseEntry.levels[normLevel] || caseEntry.levels[levelKey])) {
        var subCase = extractAnnotationFields(
          caseEntry.levels[normLevel] || caseEntry.levels[levelKey],
          epMap
        );
        if (subCase) {
          candidates.push(subCase);
        }
      }
      candidates.push(caseEntry);
    }

    var tag = null;
    var quote = "";
    var ledgerCalls = null;
    var regretTotal = null;
    for (var i = 0; i < candidates.length; i += 1) {
      var cand = candidates[i];
      if (!tag && cand.failure_tag) {
        tag = cand.failure_tag;
      }
      if (!quote && cand.analyst_quote) {
        quote = cand.analyst_quote;
      }
      if (ledgerCalls === null && cand.ledger_calls !== null && cand.ledger_calls !== undefined) {
        ledgerCalls = cand.ledger_calls;
      }
      if (regretTotal === null && cand.regret_total !== null && cand.regret_total !== undefined) {
        regretTotal = cand.regret_total;
      }
    }
    return {
      failure_tag: tag,
      analyst_quote: quote,
      ledger_calls: ledgerCalls,
      regret_total: regretTotal
    };
  }

  function extractPersonaRecord(val) {
    if (typeof val === "string") {
      return { persona_note: val.trim() };
    }
    if (!isObject(val)) {
      return null;
    }
    var note = strOrDefault(
      firstDefined(val, [
        "persona_note",
        "personaNote",
        "note",
        "persona",
        "bio",
        "quirk",
        "summary",
        "voice",
        "description"
      ]),
      ""
    );
    return {
      persona_note: note,
      name: strOrNull(firstDefined(val, ["name", "full_name", "fullName"])),
      dept: strOrNull(firstDefined(val, ["dept", "department"])),
      role: strOrNull(firstDefined(val, ["role", "title"]))
    };
  }

  function buildPersonasIndex(rawPersonas) {
    var byWorldSuspect = {};
    if (!rawPersonas) {
      return { byWorldSuspect: byWorldSuspect };
    }

    function setEntry(worldKey, suspectId, val) {
      if (!worldKey || !suspectId) {
        return;
      }
      var parsed = extractPersonaRecord(val);
      if (!parsed) {
        return;
      }
      var normWorld = normalizeTierSeedKey(worldKey);
      byWorldSuspect[normWorld + ":" + String(suspectId).trim()] = parsed;
    }

    function ingestWorldEntry(worldKey, worldVal) {
      if (!isObject(worldVal)) {
        return;
      }
      var innerMap = isObject(worldVal.suspects)
        ? worldVal.suspects
        : isObject(worldVal.employees)
        ? worldVal.employees
        : isObject(worldVal.personas)
        ? worldVal.personas
        : null;
      if (innerMap) {
        var sKeys = Object.keys(innerMap);
        for (var i = 0; i < sKeys.length; i += 1) {
          setEntry(worldKey, sKeys[i], innerMap[sKeys[i]]);
        }
        return;
      }
      if (Array.isArray(worldVal.suspects || worldVal.personas || worldVal.employees)) {
        var arr = worldVal.suspects || worldVal.personas || worldVal.employees;
        for (var j = 0; j < arr.length; j += 1) {
          var item = arr[j];
          if (isObject(item)) {
            var sid = firstDefined(item, ["id", "employee", "employee_id", "employeeId", "suspect_id", "suspectId"]);
            setEntry(worldKey, sid, item);
          }
        }
        return;
      }
      var keys = Object.keys(worldVal);
      for (var k = 0; k < keys.length; k += 1) {
        setEntry(worldKey, keys[k], worldVal[keys[k]]);
      }
    }

    if (Array.isArray(rawPersonas)) {
      for (var i = 0; i < rawPersonas.length; i += 1) {
        var row = rawPersonas[i];
        if (!isObject(row)) {
          continue;
        }
        var rowTier = strOrNull(firstDefined(row, ["tier", "difficulty"]));
        var rowSeed = firstDefined(row, ["seed", "world_seed", "worldSeed"]);
        var worldKey = strOrNull(firstDefined(row, ["world", "world_key", "worldKey"])) ||
          (rowTier !== null && rowSeed !== undefined && rowSeed !== null ? rowTier.toLowerCase() + ":" + String(rowSeed) : null);
        var sid = strOrNull(firstDefined(row, ["id", "suspect_id", "suspectId", "employee", "employee_id", "employeeId"]));
        if (worldKey && sid) {
          setEntry(worldKey, sid, row);
        } else if (worldKey) {
          ingestWorldEntry(worldKey, row);
        }
      }
      return { byWorldSuspect: byWorldSuspect };
    }

    if (isObject(rawPersonas)) {
      var listWrap = firstDefined(rawPersonas, ["personas", "items", "rows"]);
      if (Array.isArray(listWrap)) {
        return buildPersonasIndex(listWrap);
      }
      var mapSource = isObject(rawPersonas.worlds) ? rawPersonas.worlds : rawPersonas;
      var topKeys = Object.keys(mapSource);
      for (var m = 0; m < topKeys.length; m += 1) {
        var key = topKeys[m];
        var val = mapSource[key];
        var parts = key.split(":");
        if (parts.length === 3) {
          setEntry(parts[0] + ":" + parts[1], parts[2], val);
        } else if (parts.length === 2) {
          ingestWorldEntry(key, val);
        }
      }
    }
    return { byWorldSuspect: byWorldSuspect };
  }

  function normalizeVariants(rawVariants) {
    var out = [];
    if (Array.isArray(rawVariants)) {
      for (var i = 0; i < rawVariants.length; i += 1) {
        var v = rawVariants[i];
        if (!isObject(v)) {
          continue;
        }
        var recips = firstDefined(v, ["recipients", "employees", "holders", "targets"]);
        out.push({
          variant: strOrDefault(firstDefined(v, ["variant", "id", "label", "code", "name"]), String(i + 1)),
          recipients: Array.isArray(recips) ? recips.map(function (r) { return String(r); }) : []
        });
      }
      return out;
    }
    if (isObject(rawVariants)) {
      var keys = Object.keys(rawVariants);
      for (var k = 0; k < keys.length; k += 1) {
        var vKey = keys[k];
        var entry = rawVariants[vKey];
        var list = Array.isArray(entry)
          ? entry
          : isObject(entry) && Array.isArray(entry.recipients)
          ? entry.recipients
          : [];
        out.push({
          variant: String(vKey),
          recipients: list.map(function (r) { return String(r); })
        });
      }
    }
    return out;
  }

  function normalizeArgs(rawArgs) {
    if (isObject(rawArgs)) {
      return rawArgs;
    }
    if (typeof rawArgs === "string") {
      try {
        var parsed = JSON.parse(rawArgs);
        if (isObject(parsed)) {
          return parsed;
        }
      } catch (_err) {
        return { raw: rawArgs };
      }
    }
    return {};
  }

  function normalizePosterior(rawPosterior) {
    var clean = {};
    if (!isObject(rawPosterior)) {
      return clean;
    }
    var keys = Object.keys(rawPosterior);
    for (var i = 0; i < keys.length; i += 1) {
      var k = keys[i];
      var prob = toFiniteNumber(rawPosterior[k], null);
      if (prob !== null) {
        clean[k] = round6(prob);
      }
    }
    return clean;
  }

  function deriveTopFromPosterior(posterior) {
    var bestSuspect = null;
    var bestProb = 0;
    var keys = Object.keys(posterior);
    for (var i = 0; i < keys.length; i += 1) {
      var k = keys[i];
      var p = toFiniteNumber(posterior[k], 0);
      if (bestSuspect === null || p > bestProb) {
        bestSuspect = k;
        bestProb = p;
      }
    }
    return { suspect: bestSuspect, prob: bestProb };
  }

  function normalizeCase(rawCase, annotationsOrIndex, personasOrIndex, idx) {
    var raw = isObject(rawCase) ? rawCase : {};
    var annIndex =
      annotationsOrIndex && isObject(annotationsOrIndex) && annotationsOrIndex.byRunId
        ? annotationsOrIndex
        : buildAnnotationsIndex(annotationsOrIndex);
    var personasIndex =
      personasOrIndex && isObject(personasOrIndex) && isObject(personasOrIndex.byWorldSuspect)
        ? personasOrIndex
        : buildPersonasIndex(personasOrIndex);

    var tier = strOrDefault(firstDefined(raw, ["tier", "difficulty"]), "hard").toLowerCase();
    var seed = toFiniteNumber(firstDefined(raw, ["seed", "world_seed", "worldSeed"]), idx || 0);
    var id = strOrDefault(
      firstDefined(raw, ["id", "case_id", "caseId", "scenario_id", "scenarioId", "decision_id", "decisionId"]),
      tier + "-" + String(seed)
    );
    var title = strOrDefault(
      firstDefined(raw, ["title", "name", "label", "headline"]),
      "Case " + tier.toUpperCase() + " Seed " + String(seed)
    );
    var rawCompany = firstDefined(raw, ["company", "company_name", "companyName", "org", "organization"]);
    var company = isObject(rawCompany)
      ? strOrDefault(firstDefined(rawCompany, ["name", "title"]), "Canary Corp")
      : strOrDefault(rawCompany, "Canary Corp");

    var decisionDay = toFiniteNumber(
      firstDefined(raw, ["decision_day", "decisionDay", "day", "current_day", "currentDay"]),
      1
    );
    var decisionStep = toFiniteNumber(
      firstDefined(raw, ["decision_step", "decisionStep", "step", "t", "turn"]),
      0
    );
    var valueAtDecision = round4(
      toFiniteNumber(
        firstDefined(raw, [
          "value_at_decision",
          "valueAtDecision",
          "v_at_decision",
          "vAtDecision",
          "V",
          "value",
          "reward_if_correct",
          "rewardIfCorrect"
        ]),
        0.5
      )
    );
    var trueMole = strOrNull(
      firstDefined(raw, ["true_mole", "trueMole", "mole", "culprit", "ground_truth_mole", "groundTruthMole"])
    );

    var rawLeaks = firstDefined(raw, ["leaks", "leak_events", "leakEvents"]) || [];
    var leaks = (Array.isArray(rawLeaks) ? rawLeaks : []).map(function (l) {
      var item = isObject(l) ? l : {};
      return {
        day: toFiniteNumber(firstDefined(item, ["day", "leaked_day", "leakedDay"]), 1),
        doc_id: strOrDefault(firstDefined(item, ["doc_id", "docId", "document_id", "documentId", "document"]), ""),
        canary_id: strOrNull(firstDefined(item, ["canary_id", "canaryId", "trap_id", "trapId"])),
        leaked_variant: strOrNull(firstDefined(item, ["leaked_variant", "leakedVariant", "variant", "fingerprint"])),
        channel: strOrDefault(firstDefined(item, ["channel", "medium", "outlet", "source"]), "external"),
        summary: strOrDefault(firstDefined(item, ["summary", "text", "description", "headline", "body"]), "")
      };
    });

    var leakedByCanaryId = {};
    for (var lkIdx = 0; lkIdx < leaks.length; lkIdx += 1) {
      if (leaks[lkIdx].canary_id && leaks[lkIdx].leaked_variant) {
        leakedByCanaryId[leaks[lkIdx].canary_id] = leaks[lkIdx].leaked_variant;
      }
    }

    var rawCanaries = firstDefined(raw, ["canaries", "canary_traps", "canaryTraps", "traps"]) || [];
    var canaries = (Array.isArray(rawCanaries) ? rawCanaries : []).map(function (c, cIdx) {
      var item = isObject(c) ? c : {};
      var cid = strOrDefault(
        firstDefined(item, ["canary_id", "canaryId", "id", "trap_id", "trapId"]),
        "c" + String(cIdx + 1)
      );
      var lv =
        strOrNull(firstDefined(item, ["leaked_variant", "leakedVariant", "triggered_variant", "triggeredVariant"])) ||
        leakedByCanaryId[cid] ||
        null;
      return {
        canary_id: cid,
        doc_id: strOrDefault(firstDefined(item, ["doc_id", "docId", "document_id", "documentId", "document"]), ""),
        day_planted: toFiniteNumber(firstDefined(item, ["day_planted", "dayPlanted", "planted_day", "plantedDay", "day"]), 1),
        variants: normalizeVariants(firstDefined(item, ["variants", "arms", "fingerprints"])),
        leaked_variant: lv
      };
    });

    var rawLogs = firstDefined(raw, ["access_logs", "accessLogs", "logs", "audit_logs", "auditLogs"]) || [];
    var accessLogs = (Array.isArray(rawLogs) ? rawLogs : []).map(function (a) {
      var item = isObject(a) ? a : {};
      return {
        day: toFiniteNumber(firstDefined(item, ["day"]), 1),
        employee: strOrDefault(
          firstDefined(item, ["employee", "employee_id", "employeeId", "emp_id", "empId", "actor", "user"]),
          ""
        ),
        doc_id: strOrDefault(
          firstDefined(item, ["doc_id", "docId", "document_id", "documentId", "document", "resource"]),
          ""
        ),
        after_hours: Boolean(
          firstDefined(item, ["after_hours", "afterHours", "off_hours", "offHours", "late"]) || false
        ),
        action: strOrDefault(firstDefined(item, ["action", "event", "op", "kind"]), "read")
      };
    });

    var hitCountsByEmp = {};
    for (var ci = 0; ci < canaries.length; ci += 1) {
      var can = canaries[ci];
      if (!can.leaked_variant) {
        continue;
      }
      for (var vi = 0; vi < can.variants.length; vi += 1) {
        var vObj = can.variants[vi];
        if (vObj.variant === can.leaked_variant) {
          for (var ri = 0; ri < vObj.recipients.length; ri += 1) {
            var empKey = vObj.recipients[ri];
            hitCountsByEmp[empKey] = (hitCountsByEmp[empKey] || 0) + 1;
          }
        }
      }
    }

    var afterHoursByEmp = {};
    for (var ai = 0; ai < accessLogs.length; ai += 1) {
      if (accessLogs[ai].after_hours && accessLogs[ai].employee) {
        var ahEmp = accessLogs[ai].employee;
        afterHoursByEmp[ahEmp] = (afterHoursByEmp[ahEmp] || 0) + 1;
      }
    }

    var rawSuspectsSource = firstDefined(raw, ["suspects", "employees", "roster", "staff"]) || [];
    var rawSuspectList = [];
    if (Array.isArray(rawSuspectsSource)) {
      rawSuspectList = rawSuspectsSource;
    } else if (isObject(rawSuspectsSource)) {
      var sMapKeys = Object.keys(rawSuspectsSource);
      for (var sk = 0; sk < sMapKeys.length; sk += 1) {
        var sVal = rawSuspectsSource[sMapKeys[sk]];
        if (isObject(sVal)) {
          rawSuspectList.push(Object.assign({ id: sMapKeys[sk] }, sVal));
        }
      }
    }

    var worldKey = tier + ":" + String(seed);
    var suspects = rawSuspectList.map(function (s, sIdx) {
      var item = isObject(s) ? s : {};
      var sid = strOrDefault(
        firstDefined(item, ["id", "employee_id", "employeeId", "emp_id", "empId", "employee"]),
        "e" + String(sIdx + 1).padStart(2, "0")
      );
      var personaMatch = personasIndex.byWorldSuspect[worldKey + ":" + sid] || null;
      var rawHits = firstDefined(item, ["canary_hits", "canaryHits", "hits"]);
      var rawAfterHours = firstDefined(item, ["after_hours_count", "afterHoursCount", "after_hours", "afterHours"]);
      var inlinePersona = strOrDefault(
        firstDefined(item, ["persona_note", "personaNote", "persona", "bio", "quirk", "note"]),
        ""
      );
      var mergedPersona =
        personaMatch && personaMatch.persona_note ? personaMatch.persona_note : inlinePersona;
      var rawName = strOrNull(firstDefined(item, ["name", "full_name", "fullName", "display_name", "displayName"]));
      var finalName = rawName || (personaMatch && personaMatch.name) || sid;
      var finalDept =
        strOrNull(firstDefined(item, ["dept", "department", "team", "division"])) ||
        (personaMatch && personaMatch.dept) ||
        "General";
      var finalRole =
        strOrNull(firstDefined(item, ["role", "title", "job_title", "jobTitle", "position"])) ||
        (personaMatch && personaMatch.role) ||
        "Staff";

      return {
        id: sid,
        name: String(finalName).trim(),
        dept: String(finalDept).trim(),
        role: String(finalRole).trim(),
        clearance: strOrDefault(firstDefined(item, ["clearance", "access_level", "accessLevel", "level"]), "standard"),
        eliminated: Boolean(
          firstDefined(item, ["eliminated", "is_eliminated", "isEliminated", "cleared", "ruled_out"]) || false
        ),
        canary_hits:
          rawHits !== undefined ? toFiniteNumber(rawHits, 0) : hitCountsByEmp[sid] || 0,
        after_hours_count:
          rawAfterHours !== undefined ? toFiniteNumber(rawAfterHours, 0) : afterHoursByEmp[sid] || 0,
        persona_note: mergedPersona
      };
    });

    var rawCommsPrimary = firstDefined(raw, ["comms", "communications", "messages", "chatter"]);
    var rawCommsList = Array.isArray(rawCommsPrimary) ? rawCommsPrimary.slice() : [];
    if (Array.isArray(raw.interviews) && rawCommsPrimary !== raw.interviews) {
      for (var iv = 0; iv < raw.interviews.length; iv += 1) {
        var ivObj = raw.interviews[iv];
        if (isObject(ivObj)) {
          rawCommsList.push(Object.assign({ kind: ivObj.kind || "interview" }, ivObj));
        }
      }
    }
    var comms = rawCommsList.map(function (m) {
      var item = isObject(m) ? m : {};
      return {
        day: toFiniteNumber(firstDefined(item, ["day"]), 1),
        kind: strOrDefault(firstDefined(item, ["kind", "type", "channel"]), "chat"),
        speaker: strOrDefault(firstDefined(item, ["speaker", "from", "sender", "employee", "author"]), ""),
        target: strOrDefault(firstDefined(item, ["target", "to", "recipient", "audience"]), "all"),
        topic: strOrDefault(firstDefined(item, ["topic", "subject", "thread"]), ""),
        text: strOrDefault(firstDefined(item, ["text", "body", "content", "message", "quote", "response"]), "")
      };
    });

    var rawSteps = firstDefined(raw, ["tool_steps", "toolSteps", "steps", "history", "trajectory"]) || [];
    var toolSteps = (Array.isArray(rawSteps) ? rawSteps : []).map(function (st, stIdx) {
      var item = isObject(st) ? st : {};
      return {
        t: toFiniteNumber(firstDefined(item, ["t", "step", "turn", "index"]), stIdx),
        day: toFiniteNumber(firstDefined(item, ["day"]), 1),
        tool: strOrDefault(firstDefined(item, ["tool", "action", "name", "fn"]), ""),
        args: normalizeArgs(firstDefined(item, ["args", "arguments", "params", "input"])),
        summary: strOrDefault(
          firstDefined(item, ["summary", "result_summary", "resultSummary", "observation", "note"]),
          ""
        )
      };
    });

    var rawSolver = firstDefined(raw, ["solver", "reference_solver", "referenceSolver", "oracle"]) || {};
    var posterior = normalizePosterior(
      firstDefined(rawSolver, ["posterior", "posteriors", "beliefs", "probs"])
    );
    var derivedTop = deriveTopFromPosterior(posterior);
    var topSuspect =
      strOrNull(firstDefined(rawSolver, ["top_suspect", "topSuspect", "best_suspect", "bestSuspect"])) ||
      derivedTop.suspect;
    var topProb = round4(
      toFiniteNumber(
        firstDefined(rawSolver, ["top_prob", "topProb", "max_prob", "maxProb", "p_top", "pTop"]),
        derivedTop.prob
      )
    );
    if (topSuspect && posterior[topSuspect] === undefined && topProb > 0) {
      posterior[topSuspect] = topProb;
    }

    var rawBreakEven = firstDefined(rawSolver, [
      "break_even_prob",
      "breakEvenProb",
      "breakeven_prob",
      "breakevenProb"
    ]);
    var breakEvenProb =
      rawBreakEven !== undefined
        ? round4(toFiniteNumber(rawBreakEven, computeBreakEvenProb(valueAtDecision)))
        : round4(computeBreakEvenProb(valueAtDecision));

    var rawEvAccuse = firstDefined(rawSolver, [
      "ev_accuse_top",
      "evAccuseTop",
      "ev_accuse",
      "evAccuse"
    ]);
    var evAccuseTop =
      rawEvAccuse !== undefined
        ? round4(toFiniteNumber(rawEvAccuse, 0))
        : round4(computeAccusationEv(topProb, valueAtDecision));

    var rawRecCall = firstDefined(rawSolver, [
      "recommended_call",
      "recommendedCall",
      "recommendation",
      "action",
      "call"
    ]);
    var explicitEvHold = firstDefined(rawSolver, [
      "ev_hold_fire",
      "evHoldFire",
      "ev_wait",
      "evWait",
      "continuation_value",
      "continuationValue"
    ]);
    var rawSolverFinalScore = firstDefined(rawSolver, ["final_score", "finalScore", "score"]);
    var rawSolverFinalDay = firstDefined(rawSolver, ["final_day", "finalDay", "accused_day", "accusedDay"]);

    var prelimRec = rawRecCall !== undefined ? normalizeActionName(rawRecCall) : null;
    var evHoldFire;
    if (explicitEvHold !== undefined) {
      evHoldFire = round4(toFiniteNumber(explicitEvHold, 0));
    } else if (
      (prelimRec === "hold_fire" || toFiniteNumber(rawSolverFinalDay, decisionDay) > decisionDay) &&
      rawSolverFinalScore !== undefined
    ) {
      evHoldFire = round4(Math.max(0, toFiniteNumber(rawSolverFinalScore, 0)));
    } else {
      evHoldFire = 0;
    }

    var recommendedCall =
      prelimRec ||
      (evAccuseTop >= Math.max(0, evHoldFire) && topProb >= breakEvenProb ? "accuse" : "hold_fire");

    var finalAccused = strOrNull(
      firstDefined(rawSolver, ["final_accused", "finalAccused", "accused"])
    );
    if (finalAccused === null && recommendedCall === "accuse") {
      finalAccused = topSuspect;
    }
    var finalDay = toFiniteNumber(rawSolverFinalDay, decisionDay);
    var solverCorrect =
      typeof rawSolver.correct === "boolean"
        ? rawSolver.correct
        : finalAccused !== null && trueMole !== null
        ? finalAccused === trueMole
        : recommendedCall === "hold_fire";
    var finalScore =
      rawSolverFinalScore !== undefined
        ? round4(toFiniteNumber(rawSolverFinalScore, 0))
        : recommendedCall === "hold_fire"
        ? evHoldFire
        : solverCorrect
        ? valueAtDecision
        : -1.0;

    var solver = {
      posterior: posterior,
      top_suspect: topSuspect,
      top_prob: topProb,
      break_even_prob: breakEvenProb,
      ev_accuse_top: evAccuseTop,
      ev_hold_fire: evHoldFire,
      recommended_call: recommendedCall,
      final_accused: finalAccused,
      final_day: finalDay,
      final_score: finalScore,
      correct: Boolean(solverCorrect)
    };

    var rawLevelsSource =
      firstDefined(raw, ["thinking_levels", "thinkingLevels", "levels", "runs", "gemini_runs", "geminiRuns"]) || [];
    var rawLevelsList = [];
    if (Array.isArray(rawLevelsSource)) {
      rawLevelsList = rawLevelsSource;
    } else if (isObject(rawLevelsSource)) {
      var lvKeys = Object.keys(rawLevelsSource);
      for (var lk = 0; lk < lvKeys.length; lk += 1) {
        var lvObj = rawLevelsSource[lvKeys[lk]];
        if (isObject(lvObj)) {
          rawLevelsList.push(
            Object.assign(
              {
                key: lvObj.key || lvKeys[lk],
                thinking_level: lvObj.thinking_level || lvObj.thinkingLevel || lvObj.level || lvKeys[lk]
              },
              lvObj
            )
          );
        }
      }
    }

    var thinkingLevels = rawLevelsList.map(function (lv, lvIdx) {
      var item = isObject(lv) ? lv : {};
      var normLevel = normalizeLevelName(
        firstDefined(item, ["thinking_level", "thinkingLevel", "level", "key"]) ||
          THINKING_LEVELS[lvIdx] ||
          "medium"
      );
      var key = strOrDefault(firstDefined(item, ["key"]), normLevel);
      var accused = strOrNull(
        firstDefined(item, ["accused", "accused_suspect", "accusedSuspect", "final_accused", "finalAccused"])
      );
      var rawCallAtT = firstDefined(item, [
        "call_at_t",
        "callAtT",
        "call_at_decision",
        "callAtDecision",
        "decision_action",
        "decisionAction",
        "action"
      ]);
      var callAtT = rawCallAtT !== undefined
        ? normalizeActionName(rawCallAtT)
        : accused !== null
        ? "accuse"
        : "hold_fire";
      var rawAccusedDay = firstDefined(item, ["accused_day", "accusedDay", "final_day", "finalDay"]);
      var accusedDay =
        rawAccusedDay !== undefined ? toFiniteNumber(rawAccusedDay, null) : accused !== null ? decisionDay : null;
      var endReason = strOrDefault(
        firstDefined(item, ["end_reason", "endReason", "status"]),
        accused !== null ? "accused" : "horizon"
      );
      var lvCorrect =
        typeof item.correct === "boolean"
          ? item.correct
          : accused !== null && trueMole !== null
          ? accused === trueMole
          : false;
      var lvScore = round4(
        toFiniteNumber(
          firstDefined(item, ["score", "reward", "final_score", "finalScore"]),
          accused !== null ? (lvCorrect ? valueAtDecision : -1.0) : 0
        )
      );
      var runId = strOrDefault(firstDefined(item, ["run_id", "runId"]), "");
      var lvModel = strOrDefault(
        firstDefined(item, ["model"]),
        strOrDefault(firstDefined(raw, ["model", "anchor_model", "anchorModel"]), "gemini-4-carbon")
      );
      var mergedAnn = lookupAnnotation(annIndex, runId, lvModel, tier, seed, normLevel, id);
      var inlineParsed = extractAnnotationFields(item, null) || {
        failure_tag: null,
        analyst_quote: "",
        ledger_calls: null,
        regret_total: null
      };
      var resolvedLedgerCalls =
        inlineParsed.ledger_calls !== null && inlineParsed.ledger_calls !== undefined
          ? inlineParsed.ledger_calls
          : mergedAnn.ledger_calls !== null && mergedAnn.ledger_calls !== undefined
          ? mergedAnn.ledger_calls
          : null;
      var resolvedRegretTotal =
        inlineParsed.regret_total !== null && inlineParsed.regret_total !== undefined
          ? inlineParsed.regret_total
          : mergedAnn.regret_total !== null && mergedAnn.regret_total !== undefined
          ? mergedAnn.regret_total
          : null;

      return {
        key: key,
        model: lvModel,
        thinking_level: normLevel,
        call_at_t: callAtT,
        accused: accused,
        accused_day: accusedDay,
        end_reason: endReason,
        correct: Boolean(lvCorrect),
        score: lvScore,
        cost_usd: round6(toFiniteNumber(firstDefined(item, ["cost_usd", "costUsd", "cost"]), 0)),
        thinking_tokens: toFiniteNumber(
          firstDefined(item, ["thinking_tokens", "thinkingTokens", "thought_tokens", "thoughtTokens", "thinking"]),
          0
        ),
        input_tokens: toFiniteNumber(
          firstDefined(item, ["input_tokens", "inputTokens", "prompt_tokens", "promptTokens", "in"]),
          0
        ),
        output_tokens: toFiniteNumber(
          firstDefined(item, ["output_tokens", "outputTokens", "completion_tokens", "completionTokens", "out"]),
          0
        ),
        cached_tokens: toFiniteNumber(
          firstDefined(item, ["cached_tokens", "cachedTokens", "cache_read_tokens", "cacheReadTokens", "cached"]),
          0
        ),
        calls: toFiniteNumber(
          firstDefined(item, ["calls", "api_calls", "apiCalls", "tool_calls", "toolCalls", "n_calls"]),
          0
        ),
        ledger_calls: resolvedLedgerCalls,
        regret_total: resolvedRegretTotal,
        run_id: runId,
        failure_tag: inlineParsed.failure_tag || mergedAnn.failure_tag || null,
        analyst_quote: inlineParsed.analyst_quote || mergedAnn.analyst_quote || ""
      };
    });

    thinkingLevels.sort(function (a, b) {
      var ia = THINKING_LEVELS.indexOf(a.thinking_level);
      var ib = THINKING_LEVELS.indexOf(b.thinking_level);
      var ra = ia === -1 ? 999 : ia;
      var rb = ib === -1 ? 999 : ib;
      return ra - rb;
    });

    var normalizedCase = {
      id: id,
      title: title,
      tier: tier,
      seed: seed,
      company: company,
      decision_day: decisionDay,
      decision_step: decisionStep,
      value_at_decision: valueAtDecision,
      suspects: suspects,
      canaries: canaries,
      leaks: leaks,
      access_logs: accessLogs,
      comms: comms,
      tool_steps: toolSteps,
      true_mole: trueMole,
      solver: solver,
      thinking_levels: thinkingLevels
    };

    var rawCaseModel = firstNonEmptyText([firstDefined(raw, ["model", "anchor_model", "anchorModel"])]);
    if (rawCaseModel !== null) {
      normalizedCase.model = rawCaseModel;
    }
    var rawAnchorLevel = firstNonEmptyText([firstDefined(raw, ["anchor_level", "anchorLevel"])]);
    if (rawAnchorLevel !== null) {
      normalizedCase.anchor_level = normalizeLevelName(rawAnchorLevel);
    }
    var rawCrossModelCarbon = firstDefined(raw, ["cross_model_carbon", "crossModelCarbon"]);
    if (Array.isArray(rawCrossModelCarbon) || isObject(rawCrossModelCarbon)) {
      normalizedCase.cross_model_carbon = rawCrossModelCarbon;
    }
    var rawLadderMatrix = firstDefined(raw, ["ladder_matrix", "ladderMatrix"]);
    if (isObject(rawLadderMatrix) || Array.isArray(rawLadderMatrix)) {
      normalizedCase.ladder_matrix = rawLadderMatrix;
    }

    return normalizedCase;
  }

  function extractRawCaseArray(payload) {
    if (!payload) {
      return null;
    }
    if (Array.isArray(payload)) {
      return payload;
    }
    if (isObject(payload)) {
      var listCandidate = firstDefined(payload, [
        "cases",
        "scenarios",
        "decision_points",
        "decisionPoints",
        "episodes",
        "items"
      ]);
      if (Array.isArray(listCandidate)) {
        return listCandidate;
      }
      if (isObject(listCandidate)) {
        return Object.keys(listCandidate).map(function (k) {
          var v = listCandidate[k];
          return isObject(v) ? Object.assign({ id: v.id || k }, v) : v;
        });
      }
    }
    return null;
  }

  function looksLikeDirectDataset(obj) {
    if (Array.isArray(obj)) {
      return true;
    }
    if (!isObject(obj)) {
      return false;
    }
    if ("data" in obj || "fallbackData" in obj) {
      return false;
    }
    return (
      "cases" in obj ||
      "scenarios" in obj ||
      "decision_points" in obj ||
      "decisionPoints" in obj ||
      "episodes" in obj
    );
  }

  function loadDataset(rawSources) {
    var win =
      typeof window !== "undefined" && window
        ? window
        : root && isObject(root)
        ? root
        : {};

    var src;
    if (looksLikeDirectDataset(rawSources)) {
      src = { data: rawSources };
    } else if (isObject(rawSources)) {
      src = rawSources;
    } else {
      src = {};
    }

    var rawData = "data" in src ? src.data : win.OUTTHINK_DATA;
    var rawFallback = "fallbackData" in src ? src.fallbackData : win.OUTTHINK_FALLBACK_DATA;
    var rawAnnotations = "annotations" in src ? src.annotations : win.OUTTHINK_ANNOTATIONS;
    var rawPersonas = "personas" in src ? src.personas : win.OUTTHINK_PERSONAS;

    var chosenPayload = null;
    var sourceKind = "data";
    var isBootstrap = false;

    var primaryArr = rawData !== undefined && rawData !== null ? extractRawCaseArray(rawData) : null;
    var fallbackArr = rawFallback !== undefined && rawFallback !== null ? extractRawCaseArray(rawFallback) : null;

    if (primaryArr !== null && (primaryArr.length > 0 || fallbackArr === null)) {
      chosenPayload = rawData;
      sourceKind = "data";
    } else if (fallbackArr !== null) {
      chosenPayload = rawFallback;
      sourceKind = "fallback";
    } else if (
      (rawData === undefined || rawData === null) &&
      (rawFallback === undefined || rawFallback === null)
    ) {
      chosenPayload = BOOTSTRAP_FALLBACK;
      sourceKind = "bootstrap";
      isBootstrap = true;
    } else {
      chosenPayload = rawData || rawFallback || [];
      sourceKind = rawData ? "data" : "fallback";
    }

    if (isObject(chosenPayload) && chosenPayload.isBootstrapFallback === true) {
      isBootstrap = true;
      sourceKind = "bootstrap";
    }

    var rawCases = extractRawCaseArray(chosenPayload) || [];
    var annIndex = buildAnnotationsIndex(rawAnnotations);
    var personasIndex = buildPersonasIndex(rawPersonas);

    var cases = [];
    var byId = {};
    for (var i = 0; i < rawCases.length; i += 1) {
      var norm = normalizeCase(rawCases[i], annIndex, personasIndex, i);
      if (isBootstrap) {
        norm.isBootstrapFallback = true;
      }
      cases.push(norm);
      byId[norm.id] = norm;
    }

    var rawMeta = isObject(chosenPayload) && isObject(chosenPayload.meta) ? chosenPayload.meta : {};
    var meta = Object.assign({}, rawMeta, {
      source: sourceKind,
      count: cases.length,
      isBootstrapFallback: isBootstrap
    });

    return {
      cases: cases,
      count: cases.length,
      byId: byId,
      source: sourceKind,
      isFallback: sourceKind !== "data",
      isBootstrapFallback: isBootstrap,
      meta: meta
    };
  }

  function formatPct(p) {
    return (toFiniteNumber(p, 0) * 100).toFixed(1) + "%";
  }

  function evaluateCall(caseObj, judgeCall) {
    var c = isObject(caseObj) ? caseObj : {};
    var solver = isObject(c.solver) ? c.solver : {};
    var valueAtDecision = toFiniteNumber(c.value_at_decision, 0.5);
    var trueMole = strOrNull(c.true_mole);
    var topProb = toFiniteNumber(solver.top_prob, 0);
    var breakEvenProb = toFiniteNumber(
      solver.break_even_prob,
      computeBreakEvenProb(valueAtDecision, solver)
    );
    var recCall = normalizeActionName(solver.recommended_call || "hold_fire");

    var rawCall = isObject(judgeCall)
      ? judgeCall
      : typeof judgeCall === "string"
      ? { action: judgeCall }
      : {};
    var action = normalizeActionName(rawCall.action || "hold_fire");
    var suspectId = strOrNull(
      firstDefined(rawCall, ["suspectId", "suspect_id", "employee", "accused"])
    );

    var correct = false;
    var optimal = false;
    var score = 0;
    var verdictLabel = "";
    var explanation = "";

    if (action === "accuse") {
      correct = Boolean(suspectId !== null && trueMole !== null && suspectId === trueMole);
      score = correct ? Number(valueAtDecision) : -1.0;
      optimal = Boolean(correct && (recCall !== "hold_fire" || topProb >= breakEvenProb));

      if (correct && optimal) {
        verdictLabel = "OPTIMAL ACCUSATION";
        explanation =
          "Pinned true mole " +
          suspectId +
          " for +" +
          round4(valueAtDecision).toFixed(2) +
          " with posterior " +
          formatPct(topProb) +
          " clearing break-even " +
          formatPct(breakEvenProb) +
          ".";
      } else if (correct && !optimal) {
        verdictLabel = "LUCKY GUESS (BELOW BREAK-EVEN)";
        explanation =
          suspectId +
          " was the true mole (+" +
          round4(valueAtDecision).toFixed(2) +
          "), but posterior " +
          formatPct(topProb) +
          " was below break-even " +
          formatPct(breakEvenProb) +
          "; Bayesian solver held fire.";
      } else {
        verdictLabel = "FALSE ACCUSATION (-1.00)";
        explanation =
          "Accused " +
          (suspectId || "none") +
          " (-1.00 penalty); true mole was " +
          (trueMole || "unknown") +
          ". Break-even required " +
          formatPct(breakEvenProb) +
          " certainty.";
      }
    } else {
      action = "hold_fire";
      correct = Boolean(recCall === "hold_fire" || topProb < 0.95);
      optimal = Boolean(recCall === "hold_fire");

      if (topProb >= 0.98 && recCall !== "hold_fire") {
        score = Math.max(0, Number(valueAtDecision) - 0.12);
        verdictLabel = "OVER-CAUTIOUS DELAY";
        explanation =
          "Mole " +
          (trueMole || solver.top_suspect || "") +
          " was already uniquely pinned at " +
          formatPct(topProb) +
          "; waiting incurred -0.12 delay decay.";
      } else {
        var holdScoreRaw =
          solver.ev_hold_fire !== undefined && solver.ev_hold_fire !== null
            ? solver.ev_hold_fire
            : solver.final_score !== undefined && solver.final_score !== null
            ? solver.final_score
            : 0.0;
        score = Number(holdScoreRaw);
        if (optimal) {
          verdictLabel = "OPTIMAL HOLD FIRE";
          explanation =
            "Held fire with top posterior " +
            formatPct(topProb) +
            " vs break-even " +
            formatPct(breakEvenProb) +
            ", avoiding a -1.00 gamble and preserving continuation EV " +
            round4(score).toFixed(2) +
            ".";
        } else {
          verdictLabel = "CAUTIOUS HOLD FIRE";
          explanation =
            "Held fire at posterior " +
            formatPct(topProb) +
            " (solver recommended " +
            recCall +
            " above break-even " +
            formatPct(breakEvenProb) +
            ").";
        }
      }
    }

    return {
      action: action,
      suspectId: suspectId,
      correct: Boolean(correct),
      optimal: Boolean(optimal),
      score: round4(score),
      verdictLabel: verdictLabel,
      explanation: explanation,
      trueMole: trueMole,
      solver: solver,
      levelComparisons: Array.isArray(c.thinking_levels) ? c.thinking_levels : []
    };
  }

  function makeEmptyLevelBucket() {
    return {
      count: 0,
      scoreSum: 0,
      meanScore: 0,
      rightCount: 0,
      accuracy: 0,
      totalCostUsd: 0,
      totalThinkingTokens: 0,
      judgeOutscoredCount: 0
    };
  }

  function createScoreboard() {
    var recordsOrder = [];
    var recordsById = {};

    function record(caseId, evalRes, caseObj) {
      var ev = isObject(evalRes) ? evalRes : {};
      var cObj = isObject(caseObj) ? caseObj : {};
      var resolvedId = strOrDefault(
        caseId !== undefined && caseId !== null ? caseId : cObj.id,
        "case_" + String(recordsOrder.length + 1)
      );
      if (!Object.prototype.hasOwnProperty.call(recordsById, resolvedId)) {
        recordsOrder.push(resolvedId);
      }
      var stored = Object.assign({}, ev, {
        caseId: resolvedId,
        solver: isObject(cObj.solver) ? cObj.solver : isObject(ev.solver) ? ev.solver : {},
        levelComparisons: Array.isArray(cObj.thinking_levels)
          ? cObj.thinking_levels
          : Array.isArray(ev.levelComparisons)
          ? ev.levelComparisons
          : []
      });
      recordsById[resolvedId] = stored;
      return stored;
    }

    function getCaseResult(caseId) {
      var key = strOrNull(caseId);
      if (!key || !Object.prototype.hasOwnProperty.call(recordsById, key)) {
        return null;
      }
      return recordsById[key];
    }

    function getAllResults() {
      return recordsOrder.map(function (id) {
        return recordsById[id];
      });
    }

    function getSummary() {
      var casesPlayed = recordsOrder.length;
      var judgeScoreSum = 0;
      var judgeRightCount = 0;
      var judgeOptimalCount = 0;

      var solverScoreSum = 0;
      var solverRightCount = 0;

      var byLevel = {};
      for (var li = 0; li < THINKING_LEVELS.length; li += 1) {
        byLevel[THINKING_LEVELS[li]] = makeEmptyLevelBucket();
      }

      for (var i = 0; i < recordsOrder.length; i += 1) {
        var rec = recordsById[recordsOrder[i]];
        var jScore = toFiniteNumber(rec.score, 0);
        judgeScoreSum += jScore;
        if (rec.correct === true) {
          judgeRightCount += 1;
        }
        if (rec.optimal === true) {
          judgeOptimalCount += 1;
        }

        var slv = isObject(rec.solver) ? rec.solver : {};
        var sScore = toFiniteNumber(
          firstDefined(slv, ["final_score", "finalScore", "score", "ev_accuse_top", "ev_hold_fire"]),
          0
        );
        solverScoreSum += sScore;
        if (slv.correct === true) {
          solverRightCount += 1;
        }

        var levels = Array.isArray(rec.levelComparisons) ? rec.levelComparisons : [];
        for (var k = 0; k < levels.length; k += 1) {
          var lv = levels[k];
          if (!isObject(lv)) {
            continue;
          }
          var lvKey = normalizeLevelName(lv.thinking_level || lv.key || "medium");
          if (!byLevel[lvKey]) {
            byLevel[lvKey] = makeEmptyLevelBucket();
          }
          var bucket = byLevel[lvKey];
          var lvScore = toFiniteNumber(lv.score, 0);
          bucket.count += 1;
          bucket.scoreSum += lvScore;
          if (lv.correct === true) {
            bucket.rightCount += 1;
          }
          bucket.totalCostUsd += toFiniteNumber(lv.cost_usd, 0);
          bucket.totalThinkingTokens += toFiniteNumber(lv.thinking_tokens, 0);
          if (jScore > lvScore) {
            bucket.judgeOutscoredCount += 1;
          }
        }
      }

      var levelKeys = Object.keys(byLevel);
      for (var m = 0; m < levelKeys.length; m += 1) {
        var b = byLevel[levelKeys[m]];
        b.scoreSum = round4(b.scoreSum);
        b.meanScore = b.count > 0 ? round4(b.scoreSum / b.count) : 0;
        b.accuracy = b.count > 0 ? round4(b.rightCount / b.count) : 0;
        b.totalCostUsd = round6(b.totalCostUsd);
        b.totalThinkingTokens = Math.round(b.totalThinkingTokens);
      }

      return {
        casesPlayed: casesPlayed,
        judge: {
          scoreSum: round4(judgeScoreSum),
          meanScore: casesPlayed > 0 ? round4(judgeScoreSum / casesPlayed) : 0,
          rightCount: judgeRightCount,
          optimalCount: judgeOptimalCount,
          accuracy: casesPlayed > 0 ? round4(judgeRightCount / casesPlayed) : 0,
          optimalRate: casesPlayed > 0 ? round4(judgeOptimalCount / casesPlayed) : 0,
          costUsd: 0
        },
        solver: {
          scoreSum: round4(solverScoreSum),
          meanScore: casesPlayed > 0 ? round4(solverScoreSum / casesPlayed) : 0,
          rightCount: solverRightCount,
          accuracy: casesPlayed > 0 ? round4(solverRightCount / casesPlayed) : 0
        },
        byLevel: byLevel
      };
    }

    function reset() {
      recordsOrder = [];
      recordsById = {};
      return getSummary();
    }

    return {
      record: record,
      getCaseResult: getCaseResult,
      getAllResults: getAllResults,
      getSummary: getSummary,
      reset: reset
    };
  }

  var OutThinkEngine = {
    THINKING_LEVELS: THINKING_LEVELS,
    BOOTSTRAP_FALLBACK: BOOTSTRAP_FALLBACK,
    round4: round4,
    computeBreakEvenProb: computeBreakEvenProb,
    computeAccusationEv: computeAccusationEv,
    extractAnnotationFields: extractAnnotationFields,
    buildAnnotationsIndex: buildAnnotationsIndex,
    normalizeCase: normalizeCase,
    loadDataset: loadDataset,
    evaluateCall: evaluateCall,
    createScoreboard: createScoreboard
  };

  if (typeof window !== "undefined" && window) {
    window.OutThinkEngine = OutThinkEngine;
  }
  if (root && typeof root === "object") {
    root.OutThinkEngine = OutThinkEngine;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = OutThinkEngine;
  }
})(typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this);
