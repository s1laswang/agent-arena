(function () {
  "use strict";

  var VALID_TABS = ["canaries", "leaks", "access", "comms", "steps"];
  var TAB_ALIASES = {
    canary: "canaries",
    canaries: "canaries",
    traps: "canaries",
    leak: "leaks",
    leaks: "leaks",
    log: "access",
    logs: "access",
    access: "access",
    access_logs: "access",
    comm: "comms",
    comms: "comms",
    chat: "comms",
    chatter: "comms",
    messages: "comms",
    interviews: "comms",
    step: "steps",
    steps: "steps",
    tool_steps: "steps",
    history: "steps"
  };

  var LEVEL_ORDER = ["minimal", "low", "medium", "high", "xhigh"];

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = String(text);
    }
    return node;
  }

  function clearNode(node) {
    if (!node) {
      return;
    }
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function isObj(v) {
    return v !== null && typeof v === "object" && !Array.isArray(v);
  }

  function toNum(v, fallback) {
    var n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  function formatSignedScore(v) {
    var n = toNum(v, 0);
    var prefix = n > 0 ? "+" : "";
    return prefix + n.toFixed(2);
  }

  function formatPct(v) {
    var n = toNum(v, 0);
    return (n * 100).toFixed(1) + "%";
  }

  function formatUsd(v) {
    var n = toNum(v, 0);
    if (n === 0) {
      return "$0.0000";
    }
    if (Math.abs(n) < 0.01) {
      return "$" + n.toFixed(4);
    }
    return "$" + n.toFixed(3);
  }

  function formatInt(v) {
    var n = Math.round(toNum(v, 0));
    return n.toLocaleString("en-US");
  }

  function normalizeTabKey(raw) {
    if (!raw) {
      return "canaries";
    }
    var k = String(raw).trim().toLowerCase();
    return TAB_ALIASES[k] || (VALID_TABS.indexOf(k) >= 0 ? k : "canaries");
  }

  function findRawCaseRecord(caseObj) {
    if (!caseObj) {
      return null;
    }
    var pools = [window.OUTTHINK_DATA, window.OUTTHINK_FALLBACK_DATA];
    for (var p = 0; p < pools.length; p += 1) {
      var src = pools[p];
      if (!src) {
        continue;
      }
      var arr = Array.isArray(src)
        ? src
        : isObj(src) && Array.isArray(src.cases || src.scenarios || src.decision_points || src.episodes || src.items)
        ? src.cases || src.scenarios || src.decision_points || src.episodes || src.items
        : null;
      if (!arr) {
        continue;
      }
      for (var i = 0; i < arr.length; i += 1) {
        var item = arr[i];
        if (!isObj(item)) {
          continue;
        }
        var itemId = item.id || item.case_id || item.caseId || item.scenario_id;
        if (itemId && String(itemId) === String(caseObj.id)) {
          return item;
        }
        var iTier = String(item.tier || item.difficulty || "").toLowerCase();
        var iSeed = item.seed !== undefined ? item.seed : item.world_seed;
        if (iTier === String(caseObj.tier).toLowerCase() && String(iSeed) === String(caseObj.seed)) {
          return item;
        }
      }
    }
    return null;
  }

  function lookupExtraPersonaFields(caseObj, suspectId) {
    var rawPersonas = window.OUTTHINK_PERSONAS;
    if (!rawPersonas || !caseObj || !suspectId) {
      return {};
    }
    var worldKey = String(caseObj.tier || "hard").toLowerCase() + ":" + String(caseObj.seed);
    var mapRoot = isObj(rawPersonas) && isObj(rawPersonas.worlds) ? rawPersonas.worlds : rawPersonas;
    if (isObj(mapRoot)) {
      var direct = mapRoot[worldKey + ":" + suspectId];
      if (isObj(direct)) {
        return direct;
      }
      var worldEntry = mapRoot[worldKey];
      if (isObj(worldEntry)) {
        var sub = worldEntry.suspects || worldEntry.employees || worldEntry.personas || worldEntry;
        if (isObj(sub) && isObj(sub[suspectId])) {
          return sub[suspectId];
        }
        if (Array.isArray(sub)) {
          for (var i = 0; i < sub.length; i += 1) {
            var row = sub[i];
            if (isObj(row) && String(row.id || row.employee || row.suspect_id) === String(suspectId)) {
              return row;
            }
          }
        }
      }
    }
    return {};
  }

  function lookupRawAnnotationEntry(caseObj, lv) {
    var rawAnn = window.OUTTHINK_ANNOTATIONS;
    if (!rawAnn || !caseObj || !lv) {
      return null;
    }
    var runId = lv.run_id ? String(lv.run_id) : "";
    var levelKey = String(lv.thinking_level || lv.key || "medium").toLowerCase();
    var tsKey = String(caseObj.tier || "hard").toLowerCase() + ":" + String(caseObj.seed);
    var tslKey = tsKey + ":" + levelKey;

    if (Array.isArray(rawAnn)) {
      for (var i = 0; i < rawAnn.length; i += 1) {
        var r = rawAnn[i];
        if (!isObj(r)) {
          continue;
        }
        if (runId && String(r.run_id || r.runId || "") === runId) {
          return r;
        }
        var rTier = String(r.tier || r.difficulty || "").toLowerCase();
        var rSeed = r.seed !== undefined ? r.seed : r.world_seed;
        var rLvl = String(r.thinking_level || r.thinkingLevel || r.level || "").toLowerCase();
        if (rTier + ":" + String(rSeed) === tsKey && (!rLvl || rLvl === levelKey)) {
          return r;
        }
      }
      return null;
    }

    if (isObj(rawAnn)) {
      var byRun = rawAnn.by_run_id || rawAnn.byRunId;
      if (runId && isObj(byRun) && isObj(byRun[runId])) {
        return byRun[runId];
      }
      if (runId && isObj(rawAnn[runId])) {
        return rawAnn[runId];
      }
      if (isObj(rawAnn[tslKey])) {
        return rawAnn[tslKey];
      }
      var byCase = rawAnn.by_case || rawAnn.byCase;
      var caseRec = (isObj(byCase) && (byCase[caseObj.id] || byCase[tsKey])) || rawAnn[caseObj.id] || rawAnn[tsKey];
      if (isObj(caseRec)) {
        var lvMap = caseRec.levels || caseRec.thinking_levels || caseRec.by_level;
        if (isObj(lvMap) && isObj(lvMap[levelKey])) {
          return lvMap[levelKey];
        }
        return caseRec;
      }
      var list = rawAnn.annotations || rawAnn.items || rawAnn.rows || rawAnn.entries;
      if (Array.isArray(list)) {
        for (var j = 0; j < list.length; j += 1) {
          var item = list[j];
          if (!isObj(item)) {
            continue;
          }
          if (runId && String(item.run_id || item.runId || "") === runId) {
            return item;
          }
          var itTier = String(item.tier || "").toLowerCase();
          var itSeed = item.seed !== undefined ? item.seed : item.world_seed;
          var itLvl = String(item.thinking_level || item.level || "").toLowerCase();
          if (itTier + ":" + String(itSeed) === tsKey && itLvl === levelKey) {
            return item;
          }
        }
      }
    }
    return null;
  }

  function resolveAnalystDetails(caseObj, lv) {
    var extra = lookupRawAnnotationEntry(caseObj, lv) || {};
    var failureTag =
      lv.primary_failure_tag ||
      lv.failure_tag ||
      extra.primary_failure_tag ||
      extra.failure_tag ||
      extra.tag ||
      null;
    var regretRaw =
      lv.regret_total !== undefined && lv.regret_total !== null
        ? lv.regret_total
        : extra.regret_total !== undefined && extra.regret_total !== null
        ? extra.regret_total
        : null;

    var quotesArr = Array.isArray(lv.quotes)
      ? lv.quotes
      : Array.isArray(extra.quotes)
      ? extra.quotes
      : [];
    var firstQuoteObj = quotesArr.length > 0 && isObj(quotesArr[0]) ? quotesArr[0] : null;

    var quoteText = "";
    if (firstQuoteObj && (firstQuoteObj.quote || firstQuoteObj.text)) {
      quoteText = String(firstQuoteObj.quote || firstQuoteObj.text).trim();
    } else if (lv.analyst_quote) {
      quoteText = String(lv.analyst_quote).trim();
    } else if (extra.analyst_quote || extra.quote || extra.thought_quote) {
      quoteText = String(extra.analyst_quote || extra.quote || extra.thought_quote).trim();
    }

    var sourceFile =
      (firstQuoteObj && (firstQuoteObj.source_file || firstQuoteObj.sourceFile)) ||
      lv.source_file ||
      extra.source_file ||
      "";
    var quoteStep = firstQuoteObj && firstQuoteObj.step !== undefined ? firstQuoteObj.step : null;
    var quoteDay = firstQuoteObj && firstQuoteObj.day !== undefined ? firstQuoteObj.day : null;

    return {
      failureTag: failureTag ? String(failureTag) : null,
      regretTotal: regretRaw !== null ? toNum(regretRaw, null) : null,
      quoteText: quoteText,
      sourceFile: sourceFile ? String(sourceFile) : "",
      step: quoteStep,
      day: quoteDay
    };
  }

  function resolveCrossModelCarbon(caseObj) {
    var rawSource = null;
    if (caseObj && caseObj.cross_model_carbon) {
      rawSource = caseObj.cross_model_carbon;
    } else if (caseObj && isObj(caseObj.reveal) && caseObj.reveal.cross_model_carbon) {
      rawSource = caseObj.reveal.cross_model_carbon;
    } else {
      var rawCase = findRawCaseRecord(caseObj);
      if (isObj(rawCase)) {
        rawSource =
          rawCase.cross_model_carbon ||
          rawCase.crossModelCarbon ||
          (isObj(rawCase.reveal) ? rawCase.reveal.cross_model_carbon : null);
      }
    }

    if (!rawSource) {
      return [];
    }

    var entries = [];
    if (Array.isArray(rawSource)) {
      entries = rawSource.slice();
    } else if (isObj(rawSource)) {
      var keys = Object.keys(rawSource);
      for (var i = 0; i < keys.length; i += 1) {
        var k = keys[i];
        var v = rawSource[k];
        if (isObj(v)) {
          entries.push(
            Object.assign(
              {
                thinking_level: v.thinking_level || v.level || k
              },
              v
            )
          );
        }
      }
    }

    var trueMole = caseObj && caseObj.true_mole ? String(caseObj.true_mole) : null;
    var valAtT = toNum(caseObj && caseObj.value_at_decision, 0.5);

    return entries
      .filter(function (item) {
        return isObj(item);
      })
      .map(function (item) {
        var accused = item.accused || item.final_accused || null;
        var correct =
          typeof item.correct === "boolean"
            ? item.correct
            : Boolean(accused && trueMole && String(accused) === trueMole);
        var score =
          item.score !== undefined && item.score !== null
            ? toNum(item.score, 0)
            : accused
            ? correct
              ? valAtT
              : -1.0
            : 0;
        return {
          display_model: String(item.display_model || item.model || "gemini-4-carbon"),
          thinking_level: String(item.thinking_level || item.level || "low").toLowerCase(),
          accused: accused ? String(accused) : null,
          accused_day: item.accused_day !== undefined ? item.accused_day : item.final_day,
          cost_usd: toNum(item.cost_usd !== undefined ? item.cost_usd : item.cost, 0),
          thinking_tokens: toNum(
            item.thinking_tokens !== undefined ? item.thinking_tokens : item.thought_tokens,
            0
          ),
          score: score,
          correct: correct
        };
      });
  }

  function getPreDecisionEvidence(caseObj) {
    var maxDay = toNum(caseObj && caseObj.decision_day, 999);
    var maxStep = toNum(caseObj && caseObj.decision_step, 0);

    var leaks = (Array.isArray(caseObj.leaks) ? caseObj.leaks : []).filter(function (lk) {
      return toNum(lk.day, 1) <= maxDay;
    });

    var leakedVariantByCanary = {};
    for (var i = 0; i < leaks.length; i += 1) {
      if (leaks[i].canary_id && leaks[i].leaked_variant) {
        leakedVariantByCanary[leaks[i].canary_id] = leaks[i].leaked_variant;
      }
    }

    var hasAnyLeakRows = Array.isArray(caseObj.leaks) && caseObj.leaks.length > 0;
    var canaries = (Array.isArray(caseObj.canaries) ? caseObj.canaries : [])
      .filter(function (c) {
        return toNum(c.day_planted, 1) <= maxDay;
      })
      .map(function (c) {
        var lv = hasAnyLeakRows
          ? leakedVariantByCanary[c.canary_id] || c.leaked_variant || null
          : c.leaked_variant || null;
        return {
          canary_id: c.canary_id,
          doc_id: c.doc_id,
          day_planted: c.day_planted,
          variants: Array.isArray(c.variants) ? c.variants : [],
          leaked_variant: lv
        };
      });

    var accessLogs = (Array.isArray(caseObj.access_logs) ? caseObj.access_logs : []).filter(function (a) {
      return toNum(a.day, 1) <= maxDay;
    });

    var comms = (Array.isArray(caseObj.comms) ? caseObj.comms : []).filter(function (m) {
      return toNum(m.day, 1) <= maxDay;
    });

    var toolSteps = (Array.isArray(caseObj.tool_steps) ? caseObj.tool_steps : []).filter(function (st) {
      var okDay = toNum(st.day, 1) <= maxDay;
      var okStep = maxStep > 0 ? toNum(st.t, 0) <= maxStep : true;
      return okDay && okStep;
    });

    return {
      canaries: canaries,
      leaks: leaks,
      access: accessLogs,
      comms: comms,
      steps: toolSteps
    };
  }

  function computeCanaryLeakCandidateIds(caseObj, preEv) {
    var hitMap = {};
    var canaries = preEv.canaries || [];
    for (var i = 0; i < canaries.length; i += 1) {
      var can = canaries[i];
      if (!can.leaked_variant) {
        continue;
      }
      for (var v = 0; v < can.variants.length; v += 1) {
        var arm = can.variants[v];
        if (arm && arm.variant === can.leaked_variant && Array.isArray(arm.recipients)) {
          for (var r = 0; r < arm.recipients.length; r += 1) {
            hitMap[String(arm.recipients[r])] = true;
          }
        }
      }
    }

    var suspects = Array.isArray(caseObj.suspects) ? caseObj.suspects : [];
    var out = [];
    for (var s = 0; s < suspects.length; s += 1) {
      var sp = suspects[s];
      if (sp.eliminated) {
        continue;
      }
      if (toNum(sp.canary_hits, 0) > 0 || hitMap[sp.id]) {
        out.push(sp.id);
      }
    }
    return out;
  }

  function buildSafePreDecisionCaseView(caseObj, preEv) {
    return {
      id: caseObj.id,
      title: caseObj.title,
      tier: caseObj.tier,
      seed: caseObj.seed,
      company: caseObj.company,
      decision_day: caseObj.decision_day,
      decision_step: caseObj.decision_step,
      value_at_decision: caseObj.value_at_decision,
      suspects: (caseObj.suspects || []).map(function (s) {
        return {
          id: s.id,
          name: s.name,
          dept: s.dept,
          role: s.role,
          clearance: s.clearance,
          eliminated: Boolean(s.eliminated),
          canary_hits: s.canary_hits,
          after_hours_count: s.after_hours_count,
          persona_note: s.persona_note
        };
      }),
      canaries: preEv.canaries,
      leaks: preEv.leaks,
      access_logs: preEv.access,
      comms: preEv.comms,
      tool_steps: preEv.steps
    };
  }

  function boot() {
    if (!window.OutThinkEngine) {
      return;
    }

    var stageEl = document.getElementById("phaser-stage");
    var stageFallbackEl = document.getElementById("stage-fallback");
    var datasetBadgeEl = document.getElementById("dataset-badge");
    var caseSelectEl = document.getElementById("case-select");
    var btnPrevCase = document.getElementById("btn-prev-case");
    var btnNextCase = document.getElementById("btn-next-case");
    var btnResetScores = document.getElementById("btn-reset-scores");
    var scoreboardBarEl = document.getElementById("scoreboard-bar");

    var caseTierBadgeEl = document.getElementById("case-tier-badge");
    var caseTitleEl = document.getElementById("case-title");
    var caseCompanyEl = document.getElementById("case-company");
    var caseSeedBadgeEl = document.getElementById("case-seed-badge");
    var caseDayBadgeEl = document.getElementById("case-day-badge");
    var caseStepBadgeEl = document.getElementById("case-step-badge");
    var caseRewardBadgeEl = document.getElementById("case-reward-badge");
    var caseStatusPillEl = document.getElementById("case-status-pill");

    var btnHighlightSuspects = document.getElementById("btn-highlight-suspects");
    var highlightSummaryEl = document.getElementById("highlight-summary");
    var suspectRosterEl = document.getElementById("suspect-roster");
    var dossierClearanceEl = document.getElementById("dossier-clearance");
    var dossierCardEl = document.getElementById("dossier-card");
    var btnAccuse = document.getElementById("btn-accuse");
    var btnHoldFire = document.getElementById("btn-hold-fire");

    var btnFilterSuspect = document.getElementById("btn-filter-suspect");
    var evidenceCutoffNoteEl = document.getElementById("evidence-cutoff-note");
    var evidenceTabsEl = document.getElementById("evidence-tabs");
    var evidenceListEl = document.getElementById("evidence-list");
    var revealPanelEl = document.getElementById("reveal-panel");
    var provenanceSummaryEl = document.getElementById("provenance-summary");
    var assetCreditsListEl = document.getElementById("asset-credits-list");

    const dataset = window.OutThinkEngine.loadDataset();
    const scoreboard = window.OutThinkEngine.createScoreboard();

    var currentIndex = 0;
    var currentCase = dataset.cases.length > 0 ? dataset.cases[0] : null;
    var currentPreEv = currentCase ? getPreDecisionEvidence(currentCase) : null;
    var selectedSuspectId = null;
    var activeTab = "canaries";
    var highlightActive = false;
    var filterBySuspect = false;
    var focusedPodLevel = null;

    function onSelectSuspect(suspectId) {
      if (!suspectId) {
        return;
      }
      selectSuspect(String(suspectId), true);
    }

    function onSelectTab(tabKey) {
      setActiveTab(normalizeTabKey(tabKey), true);
    }

    function onSelectThinkingPod(levelKey) {
      if (!levelKey) {
        return;
      }
      focusedPodLevel = String(levelKey).trim().toLowerCase();
      if (!currentCase || !scoreboard.getCaseResult(currentCase.id)) {
        return;
      }
      var cards = revealPanelEl.querySelectorAll("[data-level-key]");
      for (var i = 0; i < cards.length; i += 1) {
        var card = cards[i];
        var matches = card.getAttribute("data-level-key") === focusedPodLevel;
        card.classList.toggle("is-pod-focused", matches);
        if (matches && typeof card.scrollIntoView === "function") {
          card.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }
    }

    const scene = window.OutThinkScene
      ? window.OutThinkScene.create(stageEl, {
          onSelectSuspect: onSelectSuspect,
          onSelectTab: onSelectTab,
          onSelectThinkingPod: onSelectThinkingPod
        })
      : null;

    function notifySceneCaseChanged(safeView, existingRes) {
      if (!scene) {
        return;
      }
      if (typeof scene.setCase === "function") {
        scene.setCase(safeView);
      } else if (typeof scene.loadCase === "function") {
        scene.loadCase(safeView);
      } else if (typeof scene.renderCase === "function") {
        scene.renderCase(safeView);
      }
      if (existingRes && typeof scene.showReveal === "function") {
        scene.showReveal(existingRes, currentCase);
      } else if (!existingRes && typeof scene.clearReveal === "function") {
        scene.clearReveal();
      }
    }

    function renderDatasetHeader() {
      var label =
        dataset.source === "data"
          ? "Verified Corpus (" + dataset.count + " Cases)"
          : dataset.source === "fallback"
          ? "Offline Replay Pack (" + dataset.count + " Cases)"
          : "Bootstrap Case (" + dataset.count + ")";
      datasetBadgeEl.textContent = label;

      clearNode(caseSelectEl);
      for (var i = 0; i < dataset.cases.length; i += 1) {
        var c = dataset.cases[i];
        var done = Boolean(scoreboard.getCaseResult(c.id));
        var opt = document.createElement("option");
        opt.value = String(i);
        opt.textContent =
          (done ? "[DONE] " : "") +
          (i + 1) +
          ". " +
          c.title +
          " (" +
          c.tier.toUpperCase() +
          " s" +
          c.seed +
          " | Day " +
          c.decision_day +
          ")";
        if (i === currentIndex) {
          opt.selected = true;
        }
        caseSelectEl.appendChild(opt);
      }

      btnPrevCase.disabled = currentIndex <= 0;
      btnNextCase.disabled = currentIndex >= dataset.cases.length - 1;
    }

    function renderScoreboard() {
      clearNode(scoreboardBarEl);
      var sum = scoreboard.getSummary();
      var played = sum.casesPlayed;

      var youTile = el("div", "score-tile score-tile-you");
      var youHead = el("div", "score-tile-head");
      youHead.appendChild(el("span", "score-actor", "YOU (JUDGE)"));
      youHead.appendChild(el("span", "pill pill-cyan", played + "/" + dataset.count));
      youTile.appendChild(youHead);
      var youMain = el("div", "score-main-row");
      youMain.appendChild(el("span", "score-points", formatSignedScore(sum.judge.scoreSum)));
      youMain.appendChild(
        el("span", "score-acc", played > 0 ? formatPct(sum.judge.accuracy) + " acc" : "No calls")
      );
      youTile.appendChild(youMain);
      var youSub = el("div", "score-sub-row");
      youSub.appendChild(
        el("span", "", played > 0 ? "Mean " + formatSignedScore(sum.judge.meanScore) : "Make a call")
      );
      youSub.appendChild(el("span", "", "$0.0000"));
      youTile.appendChild(youSub);
      scoreboardBarEl.appendChild(youTile);

      var solverTile = el("div", "score-tile score-tile-solver");
      var solverHead = el("div", "score-tile-head");
      solverHead.appendChild(el("span", "score-actor", "SOLVER"));
      solverHead.appendChild(el("span", "pill pill-emerald", "BAYES"));
      solverTile.appendChild(solverHead);
      var solverMain = el("div", "score-main-row");
      solverMain.appendChild(
        el("span", "score-points", played > 0 ? formatSignedScore(sum.solver.scoreSum) : "0.00")
      );
      solverMain.appendChild(
        el("span", "score-acc", played > 0 ? formatPct(sum.solver.accuracy) + " acc" : "Oracle")
      );
      solverTile.appendChild(solverMain);
      var solverSub = el("div", "score-sub-row");
      solverSub.appendChild(
        el("span", "", played > 0 ? "Mean " + formatSignedScore(sum.solver.meanScore) : "Reference")
      );
      solverSub.appendChild(el("span", "", "EV Optimal"));
      solverTile.appendChild(solverSub);
      scoreboardBarEl.appendChild(solverTile);

      for (var i = 0; i < LEVEL_ORDER.length; i += 1) {
        var lvKey = LEVEL_ORDER[i];
        var b = sum.byLevel[lvKey] || {
          count: 0,
          scoreSum: 0,
          meanScore: 0,
          accuracy: 0,
          totalCostUsd: 0,
          totalThinkingTokens: 0
        };
        var outscored = b.count > 0 && sum.judge.scoreSum > b.scoreSum;
        var tile = el("div", "score-tile" + (outscored ? " score-tile-beaten" : ""));
        var head = el("div", "score-tile-head");
        head.appendChild(el("span", "score-actor", lvKey));
        if (outscored) {
          head.appendChild(el("span", "pill pill-cyan", "OUT-THOUGHT"));
        } else if (b.count > 0) {
          head.appendChild(el("span", "pill pill-muted", formatPct(b.accuracy)));
        }
        tile.appendChild(head);

        var main = el("div", "score-main-row");
        main.appendChild(
          el("span", "score-points", b.count > 0 ? formatSignedScore(b.scoreSum) : "0.00")
        );
        main.appendChild(el("span", "score-acc", formatUsd(b.totalCostUsd)));
        tile.appendChild(main);

        var sub = el("div", "score-sub-row");
        sub.appendChild(
          el("span", "", b.count > 0 ? "Mean " + formatSignedScore(b.meanScore) : "Gemini")
        );
        sub.appendChild(el("span", "", formatInt(b.totalThinkingTokens) + " tok"));
        tile.appendChild(sub);

        scoreboardBarEl.appendChild(tile);
      }
    }

    function renderFallbackStageIfNeeded(candidateIds, caseResult) {
      var hasPhaserMount = Boolean(scene) && stageEl && stageEl.children.length > 0;
      if (hasPhaserMount || !currentCase) {
        stageFallbackEl.hidden = true;
        clearNode(stageFallbackEl);
        return;
      }

      stageFallbackEl.hidden = false;
      clearNode(stageFallbackEl);

      var deskGrid = el("div", "fallback-floor-grid");
      var suspects = currentCase.suspects || [];
      for (var i = 0; i < suspects.length; i += 1) {
        (function (sp) {
          var isSelected = sp.id === selectedSuspectId;
          var isHighlighted = highlightActive && candidateIds.indexOf(sp.id) >= 0;
          var cls =
            "fallback-desk" +
            (isSelected ? " is-selected" : "") +
            (isHighlighted ? " is-canary-highlight" : "") +
            (sp.eliminated ? " is-eliminated" : "");
          var btn = el("button", cls);
          btn.type = "button";
          var topLine = el("div", "ev-head");
          topLine.appendChild(el("strong", "ev-title", sp.id + " " + sp.name));
          if (caseResult && caseResult.trueMole === sp.id) {
            topLine.appendChild(el("span", "pill pill-crimson", "MOLE"));
          } else if (sp.eliminated) {
            topLine.appendChild(el("span", "pill pill-muted", "CLEARED"));
          } else if (sp.canary_hits > 0) {
            topLine.appendChild(el("span", "chip-hit-dot", sp.canary_hits + " hit"));
          }
          btn.appendChild(topLine);
          btn.appendChild(el("span", "panel-hint", sp.role + " | " + sp.dept));
          btn.addEventListener("click", function () {
            selectSuspect(sp.id, false);
          });
          deskGrid.appendChild(btn);
        })(suspects[i]);
      }
      stageFallbackEl.appendChild(deskGrid);

      var podsBar = el("div", "fallback-pods-bar");
      podsBar.appendChild(el("span", "panel-hint", "Gemini Thinking Pods:"));
      var podsGroup = el("div", "emp-inline-list");
      for (var p = 0; p < LEVEL_ORDER.length; p += 1) {
        (function (lvName) {
          var podBtn = el("button", "emp-mini-btn", lvName.toUpperCase());
          podBtn.type = "button";
          podBtn.addEventListener("click", function () {
            onSelectThinkingPod(lvName);
          });
          podsGroup.appendChild(podBtn);
        })(LEVEL_ORDER[p]);
      }
      podsBar.appendChild(podsGroup);
      stageFallbackEl.appendChild(podsBar);
    }

    function renderBriefingAndRoster() {
      if (!currentCase) {
        return;
      }
      var caseResult = scoreboard.getCaseResult(currentCase.id);
      var candidateIds = computeCanaryLeakCandidateIds(currentCase, currentPreEv);

      caseTierBadgeEl.textContent = String(currentCase.tier || "hard").toUpperCase();
      caseTitleEl.textContent = currentCase.title;
      caseCompanyEl.textContent = currentCase.company;
      caseSeedBadgeEl.textContent = "Seed " + currentCase.seed;
      caseDayBadgeEl.textContent = "Day " + currentCase.decision_day;
      caseStepBadgeEl.textContent = "Step " + currentCase.decision_step;
      caseRewardBadgeEl.textContent = "+" + toNum(currentCase.value_at_decision, 0.5).toFixed(2);

      if (caseResult) {
        caseStatusPillEl.textContent = caseResult.verdictLabel || "RESOLVED";
        caseStatusPillEl.className = "metric-val status-resolved";
      } else {
        caseStatusPillEl.textContent = "AWAITING CALL";
        caseStatusPillEl.className = "metric-val status-awaiting";
      }

      btnHighlightSuspects.classList.toggle("is-active", highlightActive);
      btnHighlightSuspects.setAttribute("aria-pressed", highlightActive ? "true" : "false");
      if (highlightActive) {
        highlightSummaryEl.textContent =
          candidateIds.length > 0
            ? "Highlighting " + candidateIds.length + " canary-hit suspect(s): " + candidateIds.join(", ")
            : "0 active suspects match leaked canary variants yet";
      } else {
        highlightSummaryEl.textContent = "Click a station or suspect badge to inspect dossier";
      }

      clearNode(suspectRosterEl);
      var suspects = currentCase.suspects || [];
      for (var i = 0; i < suspects.length; i += 1) {
        (function (sp) {
          var isSelected = sp.id === selectedSuspectId;
          var isHighlighted = highlightActive && candidateIds.indexOf(sp.id) >= 0;
          var isRevealedMole = Boolean(caseResult && caseResult.trueMole === sp.id);
          var cls =
            "suspect-chip" +
            (isSelected ? " is-selected" : "") +
            (isHighlighted ? " is-canary-highlight" : "") +
            (sp.eliminated ? " is-eliminated" : "") +
            (isRevealedMole ? " is-mole-revealed" : "");

          var chip = el("button", cls);
          chip.type = "button";
          chip.setAttribute("role", "option");
          chip.setAttribute("aria-selected", isSelected ? "true" : "false");
          chip.appendChild(el("span", "", sp.id + " " + sp.name));
          if (isRevealedMole) {
            chip.appendChild(el("span", "pill pill-crimson", "MOLE"));
          } else if (sp.eliminated) {
            chip.appendChild(el("span", "pill pill-muted", "CLR"));
          } else if (sp.canary_hits > 0) {
            chip.appendChild(el("span", "chip-hit-dot", String(sp.canary_hits)));
          }
          chip.addEventListener("click", function () {
            selectSuspect(sp.id, false);
          });
          suspectRosterEl.appendChild(chip);
        })(suspects[i]);
      }

      renderFallbackStageIfNeeded(candidateIds, caseResult);
    }

    function renderDossierAndButtons() {
      clearNode(dossierCardEl);
      if (!currentCase) {
        return;
      }

      var suspects = currentCase.suspects || [];
      var sp = null;
      for (var i = 0; i < suspects.length; i += 1) {
        if (suspects[i].id === selectedSuspectId) {
          sp = suspects[i];
          break;
        }
      }
      if (!sp && suspects.length > 0) {
        sp = suspects[0];
        selectedSuspectId = sp.id;
      }

      var caseResult = scoreboard.getCaseResult(currentCase.id);

      if (!sp) {
        dossierClearanceEl.textContent = "None";
        dossierCardEl.appendChild(el("div", "empty-state", "No suspect roster available."));
        btnAccuse.textContent = "ACCUSE SUSPECT NOW";
        btnAccuse.disabled = true;
        btnHoldFire.disabled = Boolean(caseResult);
        return;
      }

      dossierClearanceEl.textContent = "Clearance: " + String(sp.clearance || "standard");

      var topRow = el("div", "dossier-top");
      var leftInfo = el("div", "");
      leftInfo.appendChild(el("div", "dossier-id-name", sp.id + " - " + sp.name));
      leftInfo.appendChild(el("div", "dossier-role-dept", sp.role + " | " + sp.dept));
      topRow.appendChild(leftInfo);

      var badgesWrap = el("div", "emp-inline-list");
      if (caseResult && caseResult.trueMole === sp.id) {
        badgesWrap.appendChild(el("span", "pill pill-crimson", "CONFIRMED MOLE"));
      } else if (sp.eliminated) {
        badgesWrap.appendChild(el("span", "pill pill-muted", "RULED OUT"));
      } else {
        badgesWrap.appendChild(el("span", "pill pill-amber", "ACTIVE SUSPECT"));
      }
      topRow.appendChild(badgesWrap);
      dossierCardEl.appendChild(topRow);

      var leakedMatches = [];
      var canaries = currentPreEv ? currentPreEv.canaries : [];
      for (var c = 0; c < canaries.length; c += 1) {
        var can = canaries[c];
        if (!can.leaked_variant) {
          continue;
        }
        for (var v = 0; v < can.variants.length; v += 1) {
          var arm = can.variants[v];
          if (
            arm.variant === can.leaked_variant &&
            Array.isArray(arm.recipients) &&
            arm.recipients.indexOf(sp.id) >= 0
          ) {
            leakedMatches.push(can.canary_id + ":" + can.leaked_variant);
          }
        }
      }

      var commsCount = 0;
      var comms = currentPreEv ? currentPreEv.comms : [];
      for (var m = 0; m < comms.length; m += 1) {
        if (comms[m].speaker === sp.id || comms[m].target === sp.id) {
          commsCount += 1;
        }
      }

      var accessCount = 0;
      var logs = currentPreEv ? currentPreEv.access : [];
      for (var a = 0; a < logs.length; a += 1) {
        if (logs[a].employee === sp.id) {
          accessCount += 1;
        }
      }

      var statsGrid = el("div", "dossier-stats");
      var s1 = el("div", "dossier-stat");
      s1.appendChild(el("span", "dossier-stat-label", "Canary Hits"));
      s1.appendChild(el("span", "dossier-stat-val", String(sp.canary_hits)));
      statsGrid.appendChild(s1);

      var s2 = el("div", "dossier-stat");
      s2.appendChild(el("span", "dossier-stat-label", "After-Hours"));
      s2.appendChild(el("span", "dossier-stat-val", String(sp.after_hours_count)));
      statsGrid.appendChild(s2);

      var s3 = el("div", "dossier-stat");
      s3.appendChild(el("span", "dossier-stat-label", "Doc Logs"));
      s3.appendChild(el("span", "dossier-stat-val", String(accessCount)));
      statsGrid.appendChild(s3);

      var s4 = el("div", "dossier-stat");
      s4.appendChild(el("span", "dossier-stat-label", "Comms"));
      s4.appendChild(el("span", "dossier-stat-val", String(commsCount)));
      statsGrid.appendChild(s4);
      dossierCardEl.appendChild(statsGrid);

      var overlapRow = el("div", "dossier-overlaps");
      overlapRow.appendChild(el("strong", "", "Triggered Traps:"));
      if (leakedMatches.length > 0) {
        for (var lm = 0; lm < leakedMatches.length; lm += 1) {
          overlapRow.appendChild(el("span", "pill pill-amber", leakedMatches[lm]));
        }
      } else {
        overlapRow.appendChild(el("span", "panel-hint", "None triggered in pre-decision window"));
      }
      dossierCardEl.appendChild(overlapRow);

      var extraPersona = lookupExtraPersonaFields(currentCase, sp.id);
      var personaText =
        sp.persona_note ||
        extraPersona.persona_note ||
        extraPersona.bio ||
        extraPersona.quirk ||
        "No additional workplace profile recorded prior to decision point.";
      var personaBox = el("div", "dossier-persona", personaText);
      if (extraPersona.bias_cue || extraPersona.quirks) {
        var cueNote = extraPersona.bias_cue
          ? " | Surface cue: " + String(extraPersona.bias_cue)
          : "";
        personaBox.textContent = personaText + cueNote;
      }
      dossierCardEl.appendChild(personaBox);

      btnAccuse.textContent = "ACCUSE " + sp.id + " NOW";
      btnAccuse.disabled = Boolean(caseResult);
      btnHoldFire.textContent = "HOLD FIRE - KEEP INVESTIGATING";
      btnHoldFire.disabled = Boolean(caseResult);
    }

    function createEmployeeButton(empId) {
      var btn = el(
        "button",
        "emp-mini-btn" + (empId === selectedSuspectId ? " is-selected" : ""),
        empId
      );
      btn.type = "button";
      btn.addEventListener("click", function () {
        selectSuspect(empId, false);
      });
      return btn;
    }

    function renderEvidencePanel() {
      if (!currentCase || !currentPreEv) {
        return;
      }

      evidenceCutoffNoteEl.textContent =
        "Pre-decision observations up to Day " +
        currentCase.decision_day +
        (currentCase.decision_step > 0 ? ", Step " + currentCase.decision_step : "");

      btnFilterSuspect.classList.toggle("is-active", filterBySuspect);
      btnFilterSuspect.setAttribute("aria-pressed", filterBySuspect ? "true" : "false");
      btnFilterSuspect.textContent =
        filterBySuspect && selectedSuspectId
          ? "Filter: " + selectedSuspectId + " Only"
          : "Filter: All Staff";

      document.getElementById("count-canaries").textContent = String(currentPreEv.canaries.length);
      document.getElementById("count-leaks").textContent = String(currentPreEv.leaks.length);
      document.getElementById("count-access").textContent = String(currentPreEv.access.length);
      document.getElementById("count-comms").textContent = String(currentPreEv.comms.length);
      document.getElementById("count-steps").textContent = String(currentPreEv.steps.length);

      var tabButtons = evidenceTabsEl.querySelectorAll("[data-tab]");
      for (var t = 0; t < tabButtons.length; t += 1) {
        var tb = tabButtons[t];
        var isAct = tb.getAttribute("data-tab") === activeTab;
        tb.classList.toggle("is-active", isAct);
        tb.setAttribute("aria-selected", isAct ? "true" : "false");
      }

      clearNode(evidenceListEl);
      var filterId = filterBySuspect ? selectedSuspectId : null;

      if (activeTab === "canaries") {
        var canaries = currentPreEv.canaries.filter(function (c) {
          if (!filterId) {
            return true;
          }
          for (var v = 0; v < c.variants.length; v += 1) {
            if ((c.variants[v].recipients || []).indexOf(filterId) >= 0) {
              return true;
            }
          }
          return false;
        });
        if (canaries.length === 0) {
          evidenceListEl.appendChild(el("div", "empty-state", "No canary traps match current view."));
          return;
        }
        for (var ci = 0; ci < canaries.length; ci += 1) {
          var can = canaries[ci];
          var card = el("div", "ev-card" + (can.leaked_variant ? " ev-card-leaked" : ""));
          var head = el("div", "ev-head");
          head.appendChild(
            el("span", "ev-title", can.canary_id + " | " + (can.doc_id || "classified_doc"))
          );
          var badges = el("div", "emp-inline-list");
          badges.appendChild(el("span", "pill pill-muted", "Planted Day " + can.day_planted));
          if (can.leaked_variant) {
            badges.appendChild(el("span", "pill pill-crimson", "LEAKED: " + can.leaked_variant));
          } else {
            badges.appendChild(el("span", "pill pill-cyan", "UNTRIGGERED"));
          }
          head.appendChild(badges);
          card.appendChild(head);

          var vList = el("div", "variant-list");
          for (var vi = 0; vi < can.variants.length; vi += 1) {
            var arm = can.variants[vi];
            var triggered = Boolean(can.leaked_variant && arm.variant === can.leaked_variant);
            var vRow = el("div", "variant-row" + (triggered ? " variant-row-triggered" : ""));
            vRow.appendChild(
              el("span", "", "Variant " + arm.variant + (triggered ? " [LEAKED]" : ""))
            );
            var recipsWrap = el("div", "emp-inline-list");
            var recips = arm.recipients || [];
            for (var ri = 0; ri < recips.length; ri += 1) {
              recipsWrap.appendChild(createEmployeeButton(recips[ri]));
            }
            vRow.appendChild(recipsWrap);
            vList.appendChild(vRow);
          }
          card.appendChild(vList);
          evidenceListEl.appendChild(card);
        }
        return;
      }

      if (activeTab === "leaks") {
        var leaks = currentPreEv.leaks;
        if (leaks.length === 0) {
          evidenceListEl.appendChild(
            el("div", "empty-state", "No external leaks intercepted prior to decision turn.")
          );
          return;
        }
        for (var li = 0; li < leaks.length; li += 1) {
          var lk = leaks[li];
          var lCard = el("div", "ev-card ev-card-leaked");
          var lHead = el("div", "ev-head");
          lHead.appendChild(
            el("span", "ev-title", "Day " + lk.day + " | " + (lk.doc_id || "Document Leak"))
          );
          var lBadges = el("div", "emp-inline-list");
          lBadges.appendChild(el("span", "pill pill-muted", lk.channel || "external"));
          if (lk.canary_id || lk.leaked_variant) {
            lBadges.appendChild(
              el(
                "span",
                "pill pill-crimson",
                (lk.canary_id ? lk.canary_id + " " : "") +
                  (lk.leaked_variant ? "Variant " + lk.leaked_variant : "")
              )
            );
          }
          lHead.appendChild(lBadges);
          lCard.appendChild(lHead);
          if (lk.summary) {
            lCard.appendChild(el("div", "ev-body", lk.summary));
          }
          evidenceListEl.appendChild(lCard);
        }
        return;
      }

      if (activeTab === "access") {
        var logs = currentPreEv.access.filter(function (a) {
          return !filterId || a.employee === filterId;
        });
        if (logs.length === 0) {
          evidenceListEl.appendChild(el("div", "empty-state", "No audit access logs for current filter."));
          return;
        }
        for (var ai = 0; ai < logs.length; ai += 1) {
          var log = logs[ai];
          var aCard = el(
            "div",
            "ev-card" + (log.employee === selectedSuspectId ? " ev-card-selected-emp" : "")
          );
          var aHead = el("div", "ev-head");
          var leftWrap = el("div", "emp-inline-list");
          leftWrap.appendChild(el("span", "pill pill-muted", "Day " + log.day));
          if (log.employee) {
            leftWrap.appendChild(createEmployeeButton(log.employee));
          }
          leftWrap.appendChild(el("span", "ev-title", log.action + " " + log.doc_id));
          aHead.appendChild(leftWrap);
          if (log.after_hours) {
            aHead.appendChild(el("span", "pill pill-amber", "AFTER HOURS"));
          }
          aCard.appendChild(aHead);
          evidenceListEl.appendChild(aCard);
        }
        return;
      }

      if (activeTab === "comms") {
        var comms = currentPreEv.comms.filter(function (m) {
          return !filterId || m.speaker === filterId || m.target === filterId;
        });
        if (comms.length === 0) {
          evidenceListEl.appendChild(
            el("div", "empty-state", "No workplace chatter or interviews for current filter.")
          );
          return;
        }
        for (var mi = 0; mi < comms.length; mi += 1) {
          var msg = comms[mi];
          var mCard = el(
            "div",
            "ev-card" +
              (msg.speaker === selectedSuspectId || msg.target === selectedSuspectId
                ? " ev-card-selected-emp"
                : "")
          );
          var mHead = el("div", "ev-head");
          var mLeft = el("div", "emp-inline-list");
          mLeft.appendChild(el("span", "pill pill-muted", "Day " + msg.day));
          mLeft.appendChild(el("span", "pill pill-violet", msg.kind));
          if (msg.speaker) {
            mLeft.appendChild(createEmployeeButton(msg.speaker));
          }
          if (msg.target && msg.target !== "all") {
            mLeft.appendChild(el("span", "panel-hint", "to"));
            mLeft.appendChild(createEmployeeButton(msg.target));
          }
          mHead.appendChild(mLeft);
          if (msg.topic) {
            mHead.appendChild(el("span", "panel-hint", msg.topic));
          }
          mCard.appendChild(mHead);
          mCard.appendChild(el("div", "ev-body", msg.text));
          evidenceListEl.appendChild(mCard);
        }
        return;
      }

      var steps = currentPreEv.steps;
      if (steps.length === 0) {
        evidenceListEl.appendChild(
          el("div", "empty-state", "No prior tool actions executed before this turn.")
        );
        return;
      }
      for (var si = 0; si < steps.length; si += 1) {
        var st = steps[si];
        var sCard = el("div", "ev-card");
        var sHead = el("div", "ev-head");
        sHead.appendChild(el("span", "ev-title", "t=" + st.t + " (Day " + st.day + ") | " + st.tool));
        var argKeys = isObj(st.args) ? Object.keys(st.args) : [];
        if (argKeys.length > 0) {
          var pairs = [];
          for (var ak = 0; ak < argKeys.length; ak += 1) {
            var k = argKeys[ak];
            pairs.push(k + "=" + JSON.stringify(st.args[k]));
          }
          sHead.appendChild(el("span", "panel-hint", pairs.join(", ")));
        }
        sCard.appendChild(sHead);
        if (st.summary) {
          sCard.appendChild(el("div", "ev-body", st.summary));
        }
        evidenceListEl.appendChild(sCard);
      }
    }

    function findSuspectName(caseObj, suspectId) {
      if (!caseObj || !suspectId) {
        return "";
      }
      var list = caseObj.suspects || [];
      for (var i = 0; i < list.length; i += 1) {
        if (list[i].id === suspectId) {
          return list[i].name || suspectId;
        }
      }
      return suspectId;
    }

    function renderRevealShowdown(res) {
      clearNode(revealPanelEl);
      if (!res || !currentCase) {
        revealPanelEl.hidden = true;
        return;
      }
      revealPanelEl.hidden = false;

      var bannerTone = res.optimal
        ? "verdict-optimal"
        : res.correct
        ? "verdict-cautious"
        : "verdict-wrong";
      var banner = el("div", "verdict-banner " + bannerTone);

      var copy = el("div", "verdict-copy");
      var hRow = el("div", "verdict-headline-row");
      hRow.appendChild(el("h3", "verdict-title", res.verdictLabel || "DECISION RECORDED"));
      var callStr =
        res.action === "accuse"
          ? "YOUR CALL: ACCUSE " + (res.suspectId || "")
          : "YOUR CALL: HOLD FIRE";
      hRow.appendChild(el("span", "pill pill-cyan", callStr));
      hRow.appendChild(
        el(
          "span",
          res.score >= 0 ? "pill pill-emerald" : "pill pill-crimson",
          "Score " + formatSignedScore(res.score)
        )
      );
      var moleId = res.trueMole || currentCase.true_mole || "unknown";
      var moleName = findSuspectName(currentCase, moleId);
      hRow.appendChild(
        el(
          "span",
          "pill pill-crimson",
          "True Mole: " + moleId + (moleName && moleName !== moleId ? " (" + moleName + ")" : "")
        )
      );
      copy.appendChild(hRow);
      copy.appendChild(el("p", "verdict-explanation", res.explanation || ""));
      banner.appendChild(copy);

      if (currentIndex < dataset.cases.length - 1) {
        var nextBtn = el("button", "btn btn-outline-amber", "Next Scenario");
        nextBtn.type = "button";
        nextBtn.addEventListener("click", function () {
          selectCaseByIndex(currentIndex + 1);
        });
        banner.appendChild(nextBtn);
      }
      revealPanelEl.appendChild(banner);

      var solver = currentCase.solver || res.solver || {};
      var solverBox = el("div", "solver-box");
      var sHead = el("div", "ev-head");
      sHead.appendChild(el("strong", "panel-title", "Bayesian Reference Solver (Exact Posterior & Break-Even Rule)"));
      var recText =
        solver.recommended_call === "accuse"
          ? "RECOMMENDED: ACCUSE " + (solver.top_suspect || "")
          : "RECOMMENDED: HOLD FIRE";
      sHead.appendChild(el("span", "pill pill-emerald", recText));
      solverBox.appendChild(sHead);

      var sGrid = el("div", "solver-metrics-grid");
      var sm1 = el("div", "solver-stat");
      sm1.appendChild(el("span", "metric-label", "Top Posterior"));
      sm1.appendChild(
        el(
          "strong",
          "metric-val",
          (solver.top_suspect ? solver.top_suspect + " @ " : "") + formatPct(solver.top_prob)
        )
      );
      sGrid.appendChild(sm1);

      var sm2 = el("div", "solver-stat");
      sm2.appendChild(el("span", "metric-label", "Break-Even Threshold"));
      sm2.appendChild(el("strong", "metric-val", formatPct(solver.break_even_prob)));
      sGrid.appendChild(sm2);

      var sm3 = el("div", "solver-stat");
      sm3.appendChild(el("span", "metric-label", "EV Accuse vs Hold"));
      sm3.appendChild(
        el(
          "strong",
          "metric-val",
          formatSignedScore(solver.ev_accuse_top) + " vs " + formatSignedScore(solver.ev_hold_fire)
        )
      );
      sGrid.appendChild(sm3);

      var sm4 = el("div", "solver-stat");
      sm4.appendChild(el("span", "metric-label", "Solver Final Outcome"));
      sm4.appendChild(
        el(
          "strong",
          "metric-val",
          formatSignedScore(solver.final_score) +
            (solver.final_accused ? " (" + solver.final_accused + ", Day " + solver.final_day + ")" : "")
        )
      );
      sGrid.appendChild(sm4);
      solverBox.appendChild(sGrid);

      var postObj = isObj(solver.posterior) ? solver.posterior : {};
      var postKeys = Object.keys(postObj).sort(function (a, b) {
        return toNum(postObj[b], 0) - toNum(postObj[a], 0);
      });
      if (postKeys.length > 0) {
        var postStrip = el("div", "posterior-strip");
        postStrip.appendChild(el("span", "panel-hint", "Posterior Beliefs:"));
        for (var pk = 0; pk < postKeys.length; pk += 1) {
          var empKey = postKeys[pk];
          var probVal = toNum(postObj[empKey], 0);
          if (probVal <= 0 && pk >= 5) {
            continue;
          }
          var pCls = "posterior-pill" + (empKey === moleId ? " posterior-pill-mole" : "");
          postStrip.appendChild(el("span", pCls, empKey + ": " + formatPct(probVal)));
        }
        solverBox.appendChild(postStrip);
      }
      revealPanelEl.appendChild(solverBox);

      var levels = Array.isArray(currentCase.thinking_levels) ? currentCase.thinking_levels : [];
      var lvHeader = el("div", "levels-section-head");
      lvHeader.appendChild(
        el("strong", "panel-title", "Gemini Thinking Ladder Showdown (Same World, Same Evidence)")
      );
      lvHeader.appendChild(
        el("span", "panel-hint", "Real recorded episodes with token spend, USD cost, and Failure Analyst forensics")
      );
      revealPanelEl.appendChild(lvHeader);

      var lvGrid = el("div", "levels-grid");
      for (var li = 0; li < levels.length; li += 1) {
        var lv = levels[li];
        var lvKey = String(lv.thinking_level || lv.key || "medium").toLowerCase();
        var cardCls =
          "level-card " +
          (lv.correct ? "level-card-right" : "level-card-wrong") +
          (focusedPodLevel === lvKey ? " is-pod-focused" : "");
        var card = el("div", cardCls);
        card.setAttribute("data-level-key", lvKey);

        var cTop = el("div", "level-card-top");
        cTop.appendChild(el("span", "level-name", lvKey));
        cTop.appendChild(
          el(
            "span",
            lv.correct ? "pill pill-emerald" : "pill pill-crimson",
            lv.correct ? "RIGHT" : "WRONG"
          )
        );
        card.appendChild(cTop);

        card.appendChild(
          el("div", "level-model", String(lv.display_model || lv.model || "gemini-4-carbon"))
        );

        var kv = el("div", "level-kv-grid");
        var kv1 = el("div", "level-kv-item");
        kv1.appendChild(el("span", "level-kv-label", "Accused"));
        var accText = lv.accused
          ? lv.accused + (lv.accused_day !== null && lv.accused_day !== undefined ? " (d" + lv.accused_day + ")" : "")
          : "None (" + (lv.end_reason || "horizon") + ")";
        kv1.appendChild(el("span", "level-kv-val", accText));
        kv.appendChild(kv1);

        var kv2 = el("div", "level-kv-item");
        kv2.appendChild(el("span", "level-kv-label", "Score"));
        kv2.appendChild(el("span", "level-kv-val", formatSignedScore(lv.score)));
        kv.appendChild(kv2);

        var kv3 = el("div", "level-kv-item");
        kv3.appendChild(el("span", "level-kv-label", "API Cost"));
        kv3.appendChild(el("span", "level-kv-val", formatUsd(lv.cost_usd)));
        kv.appendChild(kv3);

        var kv4 = el("div", "level-kv-item");
        kv4.appendChild(el("span", "level-kv-label", "Thinking Tok"));
        kv4.appendChild(el("span", "level-kv-val", formatInt(lv.thinking_tokens)));
        kv.appendChild(kv4);
        card.appendChild(kv);

        var ann = resolveAnalystDetails(currentCase, lv);
        var tagRow = el("div", "level-tags-row");
        tagRow.appendChild(
          el(
            "span",
            "pill pill-muted",
            "t-call: " + (lv.call_at_t === "accuse" ? "ACCUSE" : "HOLD FIRE")
          )
        );
        if (ann.failureTag) {
          tagRow.appendChild(el("span", "pill pill-amber", ann.failureTag));
        }
        if (ann.regretTotal !== null && ann.regretTotal > 0) {
          tagRow.appendChild(el("span", "pill pill-crimson", "Regret " + ann.regretTotal.toFixed(2)));
        }
        card.appendChild(tagRow);

        if (ann.quoteText || ann.sourceFile) {
          var qBox = el("blockquote", "analyst-quote-box");
          if (ann.quoteText) {
            qBox.appendChild(el("span", "", "\"" + ann.quoteText + "\""));
          }
          if (ann.sourceFile || ann.day !== null || ann.step !== null) {
            var qMeta = el("div", "quote-source-row");
            if (ann.sourceFile) {
              qMeta.appendChild(el("span", "pill pill-violet", ann.sourceFile));
            }
            var stepDayParts = [];
            if (ann.day !== null && ann.day !== undefined) {
              stepDayParts.push("Day " + ann.day);
            }
            if (ann.step !== null && ann.step !== undefined) {
              stepDayParts.push("Step " + ann.step);
            }
            if (stepDayParts.length > 0) {
              qMeta.appendChild(el("span", "", stepDayParts.join(" | ")));
            }
            qBox.appendChild(qMeta);
          }
          card.appendChild(qBox);
        }

        lvGrid.appendChild(card);
      }
      revealPanelEl.appendChild(lvGrid);

      var carbonRows = resolveCrossModelCarbon(currentCase);
      if (carbonRows.length > 0) {
        var cStrip = el("div", "carbon-strip");
        cStrip.appendChild(
          el("h4", "carbon-strip-title", "Same World on gemini-4-carbon (low vs high)")
        );
        var cRow = el("div", "carbon-cards-row");
        for (var ci = 0; ci < carbonRows.length; ci += 1) {
          var cr = carbonRows[ci];
          var cItem = el("div", "carbon-item");
          var cLeft = el("div", "emp-inline-list");
          cLeft.appendChild(el("strong", "", cr.display_model));
          cLeft.appendChild(el("span", "pill pill-violet", cr.thinking_level));
          cLeft.appendChild(
            el(
              "span",
              "",
              "Accused: " +
                (cr.accused
                  ? cr.accused + (cr.accused_day !== undefined && cr.accused_day !== null ? " (d" + cr.accused_day + ")" : "")
                  : "none")
            )
          );
          cItem.appendChild(cLeft);

          var cRight = el("div", "emp-inline-list");
          cRight.appendChild(el("span", "", formatUsd(cr.cost_usd)));
          cRight.appendChild(el("span", "", formatInt(cr.thinking_tokens) + " tok"));
          cRight.appendChild(el("strong", "", formatSignedScore(cr.score)));
          cRight.appendChild(
            el(
              "span",
              cr.correct ? "pill pill-emerald" : "pill pill-crimson",
              cr.correct ? "RIGHT" : "WRONG"
            )
          );
          cItem.appendChild(cRight);
          cRow.appendChild(cItem);
        }
        cStrip.appendChild(cRow);
        revealPanelEl.appendChild(cStrip);
      }
    }

    function renderProvenanceFooter() {
      var meta = isObj(dataset.meta) ? dataset.meta : {};
      var parts = [
        "Deterministic Replay Benchmark (0 live API calls in browser)",
        "Loaded " + dataset.count + " scenario(s) from " + dataset.source + " bundle"
      ];
      if (meta.total_episodes) {
        parts.push(formatInt(meta.total_episodes) + " recorded ladder episodes");
      }
      if (meta.total_cost_usd !== undefined) {
        parts.push("Corpus API spend " + formatUsd(meta.total_cost_usd));
      }
      provenanceSummaryEl.textContent = parts.join(" | ");

      clearNode(assetCreditsListEl);
      var assetsObj = window.OUTTHINK_ASSETS;
      var packsRaw = isObj(assetsObj) ? assetsObj.packs : null;
      var packsList = [];
      if (Array.isArray(packsRaw)) {
        packsList = packsRaw;
      } else if (isObj(packsRaw)) {
        var keys = Object.keys(packsRaw);
        for (var i = 0; i < keys.length; i += 1) {
          var v = packsRaw[keys[i]];
          if (isObj(v)) {
            packsList.push(Object.assign({ id: v.id || keys[i] }, v));
          }
        }
      }

      if (packsList.length === 0) {
        assetCreditsListEl.appendChild(
          el("span", "credit-pill", "CC0 Sprites & UI Packs: Kenney.nl / OpenGameArt (see docs/demo/ASSETS.md)")
        );
        return;
      }

      for (var p = 0; p < packsList.length; p += 1) {
        var pk = packsList[p];
        if (!isObj(pk)) {
          continue;
        }
        var pName = pk.name || pk.title || pk.id || "Asset Pack " + (p + 1);
        var pAuthor = pk.author || pk.creator || "CC0 Author";
        var pLicense = pk.license || "CC0";
        assetCreditsListEl.appendChild(
          el("span", "credit-pill", pName + " by " + pAuthor + " (" + pLicense + ")")
        );
      }
    }

    function selectSuspect(suspectId, fromScene) {
      if (!currentCase) {
        return;
      }
      selectedSuspectId = suspectId;
      if (!fromScene && scene) {
        if (typeof scene.selectSuspect === "function") {
          scene.selectSuspect(suspectId);
        } else if (typeof scene.setSelectedSuspect === "function") {
          scene.setSelectedSuspect(suspectId);
        }
      }
      renderBriefingAndRoster();
      renderDossierAndButtons();
      if (filterBySuspect || activeTab === "access" || activeTab === "comms") {
        renderEvidencePanel();
      }
    }

    function setActiveTab(tabKey, fromScene) {
      activeTab = normalizeTabKey(tabKey);
      if (!fromScene && scene && typeof scene.setActiveTab === "function") {
        scene.setActiveTab(activeTab);
      }
      renderEvidencePanel();
    }

    function selectCaseByIndex(index) {
      if (dataset.cases.length === 0) {
        return;
      }
      var bounded = Math.max(0, Math.min(dataset.cases.length - 1, index));
      currentIndex = bounded;
      currentCase = dataset.cases[currentIndex];
      currentPreEv = getPreDecisionEvidence(currentCase);
      highlightActive = false;
      focusedPodLevel = null;

      var suspects = currentCase.suspects || [];
      var defaultSuspect = suspects.length > 0 ? suspects[0].id : null;
      for (var i = 0; i < suspects.length; i += 1) {
        if (!suspects[i].eliminated) {
          defaultSuspect = suspects[i].id;
          break;
        }
      }
      selectedSuspectId = defaultSuspect;

      if (scene && typeof scene.setHighlightCandidates === "function") {
        scene.setHighlightCandidates(undefined, false);
      }

      var existingRes = scoreboard.getCaseResult(currentCase.id);
      var safeView = buildSafePreDecisionCaseView(currentCase, currentPreEv);
      notifySceneCaseChanged(safeView, existingRes);

      renderDatasetHeader();
      renderBriefingAndRoster();
      renderDossierAndButtons();
      renderEvidencePanel();

      if (existingRes) {
        renderRevealShowdown(existingRes);
      } else {
        clearNode(revealPanelEl);
        revealPanelEl.hidden = true;
      }
    }

    function submitJudgeCall(call) {
      if (!currentCase || scoreboard.getCaseResult(currentCase.id)) {
        return;
      }
      const res = window.OutThinkEngine.evaluateCall(currentCase, call);
      scoreboard.record(currentCase.id, res, currentCase);
      if (scene && typeof scene.showReveal === "function") {
        scene.showReveal(res, currentCase);
      }

      renderDatasetHeader();
      renderScoreboard();
      renderBriefingAndRoster();
      renderDossierAndButtons();
      renderRevealShowdown(res);

      if (typeof revealPanelEl.scrollIntoView === "function") {
        revealPanelEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    }

    caseSelectEl.addEventListener("change", function () {
      selectCaseByIndex(toNum(caseSelectEl.value, 0));
    });

    btnPrevCase.addEventListener("click", function () {
      if (currentIndex > 0) {
        selectCaseByIndex(currentIndex - 1);
      }
    });

    btnNextCase.addEventListener("click", function () {
      if (currentIndex < dataset.cases.length - 1) {
        selectCaseByIndex(currentIndex + 1);
      }
    });

    btnResetScores.addEventListener("click", function () {
      scoreboard.reset();
      selectCaseByIndex(currentIndex);
      renderScoreboard();
    });

    btnHighlightSuspects.addEventListener("click", function () {
      if (!currentCase || !currentPreEv) {
        return;
      }
      highlightActive = !highlightActive;
      var candidateIds = computeCanaryLeakCandidateIds(currentCase, currentPreEv);
      if (scene && typeof scene.setHighlightCandidates === "function") {
        scene.setHighlightCandidates(highlightActive ? candidateIds : undefined, highlightActive);
      }
      renderBriefingAndRoster();
    });

    btnFilterSuspect.addEventListener("click", function () {
      filterBySuspect = !filterBySuspect;
      renderEvidencePanel();
    });

    evidenceTabsEl.addEventListener("click", function (ev) {
      var target = ev.target && ev.target.closest ? ev.target.closest("[data-tab]") : null;
      if (target) {
        setActiveTab(target.getAttribute("data-tab"), false);
      }
    });

    btnAccuse.addEventListener("click", function () {
      if (!selectedSuspectId) {
        return;
      }
      submitJudgeCall({ action: "accuse", suspectId: selectedSuspectId });
    });

    btnHoldFire.addEventListener("click", function () {
      submitJudgeCall({ action: "hold_fire" });
    });

    renderScoreboard();
    renderProvenanceFooter();
    if (currentCase) {
      selectCaseByIndex(0);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
