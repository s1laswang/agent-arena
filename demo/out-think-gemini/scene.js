(function (root) {
  "use strict";

  var GRID_W = 960;
  var GRID_H = 520;
  var POD_LEVELS = ["minimal", "low", "medium", "high", "xhigh"];
  var POD_LABELS = { minimal: "MINIMAL", low: "LOW", medium: "MEDIUM", high: "HIGH", xhigh: "XHIGH" };
  var POD_COLORS = { minimal: "#94a3b8", low: "#38bdf8", medium: "#a78bfa", high: "#f59e0b", xhigh: "#34d399" };
  var DEPT_PALETTE = ["#22d3ee", "#f59e0b", "#a78bfa", "#34d399", "#fb7185", "#60a5fa", "#facc15", "#c084fc"];
  var SUSPECT_HAIR = ["#f8fafc", "#fbbf24", "#ef4444", "#9a3412", "#cbd5e1", "#38bdf8", "#c084fc", "#fb923c"];
  var SUSPECT_SUIT = ["#2563eb", "#0d9488", "#4f46e5", "#be123c", "#475569", "#059669", "#7c3aed", "#b45309"];
  var SPRITE_KEYS = [
    "floor_tile", "wall_tile", "window_night", "door", "desk", "chair",
    "evidence_board", "filing_cabinet", "terminal", "server_rack", "lamp",
    "detective", "suspect_0", "suspect_1", "suspect_2", "suspect_3",
    "suspect_4", "suspect_5", "suspect_6", "suspect_7",
    "agent_minimal", "agent_low", "agent_medium", "agent_high", "agent_xhigh",
    "pod_locked", "pod_unlocked", "icon_correct", "icon_wrong"
  ];
  var PROPS = [
    { key: "canaries", label: "CORKBOARD", sprite: "evidence_board", x: 96, y: 10, w: 114, h: 74 },
    { key: "leaks", label: "LEAK WIRE", sprite: "evidence_board", x: 222, y: 10, w: 114, h: 74 },
    { key: "access", label: "ACCESS", sprite: "server_rack", x: 348, y: 10, w: 114, h: 74 },
    { key: "comms", label: "COMMS CRT", sprite: "terminal", x: 474, y: 10, w: 114, h: 74 },
    { key: "steps", label: "CABINET", sprite: "filing_cabinet", x: 600, y: 10, w: 110, h: 74 }
  ];

  function nowMs() {
    return typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();
  }

  function clipText(str, maxLen) {
    var s = String(str == null ? "" : str).replace(/\s+/g, " ").trim();
    return s.length <= maxLen ? s : s.slice(0, Math.max(1, maxLen - 2)) + "..";
  }

  function fillBox(ctx, color, x, y, w, h) {
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  }

  function strokeBox(ctx, color, lw, x, y, w, h) {
    ctx.strokeStyle = color;
    ctx.lineWidth = lw;
    ctx.strokeRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  }

  function drawText(ctx, txt, x, y, color, font, align) {
    ctx.fillStyle = color;
    ctx.font = font || "10px monospace";
    ctx.textAlign = align || "left";
    ctx.fillText(txt, Math.round(x), Math.round(y));
  }

  function loadSpriteBank(onReady) {
    var bank = {};
    var assets = (typeof window !== "undefined" && window.OUTTHINK_ASSETS) || (root && root.OUTTHINK_ASSETS) || null;
    var sprites = assets && assets.sprites ? assets.sprites : null;
    if (!sprites || typeof Image === "undefined") return bank;
    var keys = SPRITE_KEYS.concat(Object.keys(sprites));
    for (var i = 0; i < keys.length; i += 1) {
      var k = keys[i];
      if (bank[k] || !sprites[k]) continue;
      var src = sprites[k].dataUri || sprites[k].path || "";
      if (!src) continue;
      var img = new Image();
      if (typeof onReady === "function") img.onload = onReady;
      img.src = src;
      bank[k] = { img: img, meta: sprites[k] };
    }
    return bank;
  }

  function drawAsset(ctx, bank, key, dx, dy, dw, dh, tick) {
    var rec = bank && bank[key];
    if (!rec || !rec.img || !rec.img.complete) return false;
    var nw = rec.img.naturalWidth || rec.img.width || 0;
    var nh = rec.img.naturalHeight || rec.img.height || 0;
    if (nw <= 0 || nh <= 0) return false;
    var meta = rec.meta || {};
    var frames = meta.frames && meta.frames > 1 ? meta.frames : 1;
    var fw = meta.frameWidth || Math.max(1, Math.floor(nw / frames));
    var fh = meta.frameHeight || nh;
    var fIdx = frames > 1 ? Math.floor(tick / 16) % frames : 0;
    ctx.drawImage(rec.img, fIdx * fw, 0, fw, fh, Math.round(dx), Math.round(dy), Math.round(dw), Math.round(dh));
    return true;
  }

  function drawProp(ctx, bank, kind, x, y, w, h, tick) {
    if (drawAsset(ctx, bank, kind, x, y, w, h, tick)) return;
    if (kind === "window_night") {
      fillBox(ctx, "#090d1a", x, y, w, h);
      fillBox(ctx, "#1e293b", x + 4, y + h - 18, 10, 18);
      fillBox(ctx, "#1e293b", x + 16, y + h - 26, 12, 26);
      fillBox(ctx, "#fde047", x + 19, y + h - 21, 3, 3);
      fillBox(ctx, "#38bdf8", x + 10, y + 5 + (Math.floor(tick / 6) % 10), 1, 5);
      strokeBox(ctx, "#475569", 2, x + 1, y + 1, w - 2, h - 2);
    } else if (kind === "door") {
      fillBox(ctx, "#334155", x, y, w, h);
      fillBox(ctx, "#1e293b", x + 4, y + 4, w - 8, h * 0.42);
      fillBox(ctx, "#1e293b", x + 4, y + h * 0.52, w - 8, h * 0.4);
      fillBox(ctx, "#fbbf24", x + w - 7, y + h * 0.5, 3, 3);
    } else if (kind === "evidence_board") {
      fillBox(ctx, "#78350f", x, y, w, h);
      fillBox(ctx, "#b45309", x + 3, y + 3, w - 6, h - 6);
      fillBox(ctx, "#fef3c7", x + 6, y + 6, 10, 8);
      fillBox(ctx, "#fef3c7", x + w - 16, y + 8, 9, 8);
      fillBox(ctx, "#fecdd3", x + w * 0.42, y + h - 14, 10, 8);
      ctx.strokeStyle = "#ef4444";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x + 11, y + 10); ctx.lineTo(x + w * 0.47, y + h - 10); ctx.lineTo(x + w - 11, y + 12);
      ctx.stroke();
    } else if (kind === "server_rack") {
      fillBox(ctx, "#0f172a", x, y, w, h);
      strokeBox(ctx, "#475569", 1, x + 1, y + 1, w - 2, h - 2);
      for (var r = 0; r < 4; r += 1) {
        var ry = y + 5 + r * Math.floor((h - 8) / 4);
        fillBox(ctx, "#1e293b", x + 4, ry, w - 8, 5);
        fillBox(ctx, (Math.floor(tick / 12) + r) % 2 === 0 ? "#22c55e" : "#38bdf8", x + 6, ry + 1, 3, 3);
        fillBox(ctx, "#f59e0b", x + 12, ry + 1, 3, 3);
      }
    } else if (kind === "terminal") {
      fillBox(ctx, "#334155", x + 2, y + 2, w - 4, h - 8);
      fillBox(ctx, "#052e16", x + 5, y + 5, w - 10, h - 14);
      fillBox(ctx, "#4ade80", x + 8, y + 8, Math.max(6, w - 18), 2);
      fillBox(ctx, "#4ade80", x + 8, y + 13, Math.max(4, w - 24), 2);
      fillBox(ctx, "#475569", x, y + h - 5, w, 4);
    } else if (kind === "filing_cabinet") {
      fillBox(ctx, "#475569", x + 4, y + 2, w - 8, h - 4);
      for (var d = 0; d < 3; d += 1) {
        var dy = y + 5 + d * Math.floor((h - 8) / 3);
        fillBox(ctx, "#334155", x + 6, dy, w - 12, Math.floor((h - 14) / 3));
        fillBox(ctx, "#cbd5e1", x + w / 2 - 4, dy + 3, 8, 2);
      }
    } else if (kind === "desk") {
      fillBox(ctx, "#451a03", x, y + 4, w, h - 4);
      fillBox(ctx, "#78350f", x, y, w, h - 4);
      fillBox(ctx, "#92400e", x + 2, y + 1, w - 4, 2);
    } else if (kind === "chair") {
      fillBox(ctx, "#1e293b", x + 2, y, w - 4, h);
      fillBox(ctx, "#334155", x, y + 3, w, h - 5);
    } else if (kind === "lamp") {
      fillBox(ctx, "#f59e0b", x + w / 2 - 1, y + 5, 3, h - 7);
      fillBox(ctx, "#f59e0b", x + 3, y + h - 3, w - 6, 3);
      fillBox(ctx, "#16a34a", x + 1, y + 1, w - 2, 5);
    }
  }

  function drawActor(ctx, bank, key, variant, x, y, w, h, tick, accent) {
    if (drawAsset(ctx, bank, key, x, y, w, h, tick)) return;
    var py = y + (Math.floor(tick / 20) % 2);
    if (variant === "detective") {
      fillBox(ctx, "#1e293b", x + 2, py, w - 4, 4);
      fillBox(ctx, "#1e293b", x, py + 3, w, 2);
      fillBox(ctx, "#f59e0b", x + 3, py + 2, w - 6, 1);
      fillBox(ctx, "#fed7aa", x + 4, py + 5, w - 8, 5);
      fillBox(ctx, "#a16207", x + 2, py + 10, w - 4, h - 10);
      fillBox(ctx, "#78350f", x + 5, py + 11, w - 10, h - 12);
    } else if (variant === "agent") {
      fillBox(ctx, accent || "#38bdf8", x + 3, py + 1, w - 6, 6);
      fillBox(ctx, "#0f172a", x + 4, py + 3, w - 8, 2);
      fillBox(ctx, "#334155", x + 2, py + 7, w - 4, h - 7);
      fillBox(ctx, accent || "#38bdf8", x + 5, py + 9, w - 10, 3);
    } else {
      var idx = typeof variant === "number" ? variant % 8 : 0;
      fillBox(ctx, SUSPECT_HAIR[idx], x + 3, py, w - 6, 4);
      fillBox(ctx, "#fed7aa", x + 3, py + 4, w - 6, 5);
      fillBox(ctx, SUSPECT_SUIT[idx], x + 1, py + 9, w - 2, Math.max(4, h - 9));
      fillBox(ctx, "#e2e8f0", x + w / 2 - 1, py + 9, 2, 4);
    }
  }

  function extractSuspects(caseObj) {
    if (!caseObj || typeof caseObj !== "object") return [];
    var rawList = Array.isArray(caseObj.suspects) ? caseObj.suspects : Array.isArray(caseObj.employees) ? caseObj.employees : [];
    var quoteByEmp = {};
    var comms = Array.isArray(caseObj.comms) ? caseObj.comms : Array.isArray(caseObj.chatter) ? caseObj.chatter : [];
    for (var c = 0; c < comms.length; c += 1) {
      var msg = comms[c] || {};
      var who = msg.speaker || msg.from || msg.sender || msg.employee || msg.suspect_id || "";
      var body = msg.text || msg.body || msg.message || msg.quote || "";
      if (who && body && !quoteByEmp[who]) quoteByEmp[who] = String(body);
    }
    return rawList.map(function (item, i) {
      var s = item || {};
      var id = String(s.id || s.employee_id || s.employeeId || ("e" + String(i + 1).padStart(2, "0")));
      var name = String(s.name || s.full_name || id).trim();
      var parts = name.split(/\s+/);
      var shortName = parts.length > 1 ? parts[0].charAt(0) + "." + parts[parts.length - 1] : name;
      var dept = String(s.dept || s.department || s.team || "General").trim();
      var role = String(s.role || s.title || "Staff").trim();
      var quote = quoteByEmp[id] || s.quote || s.persona_note || s.personaNote || (role + " [" + dept + "]");
      return {
        id: id, name: name, shortName: clipText(shortName, 10), dept: dept, role: role,
        eliminated: Boolean(s.eliminated || s.is_eliminated || s.cleared || s.ruled_out),
        hits: Number(s.canary_hits != null ? s.canary_hits : s.hits || 0) || 0,
        afterHours: Number(s.after_hours_count != null ? s.after_hours_count : s.after_hours || 0) || 0,
        quote: clipText(quote, 44), variant: i % 8, spriteKey: "suspect_" + String(i % 8)
      };
    });
  }

  function buildStations(suspects) {
    var total = suspects.length;
    if (total === 0) return { stations: [], rowBands: [] };
    var deptOrder = [];
    var deptBuckets = {};
    for (var i = 0; i < total; i += 1) {
      var d = suspects[i].dept || "General";
      if (!deptBuckets[d]) { deptBuckets[d] = []; deptOrder.push(d); }
      deptBuckets[d].push(suspects[i]);
    }
    var maxCols = total <= 12 ? 4 : total <= 18 ? 6 : total <= 28 ? 7 : total <= 36 ? 8 : 10;
    var rows = [];
    for (var di = 0; di < deptOrder.length; di += 1) {
      var dName = deptOrder[di];
      var list = deptBuckets[dName];
      var color = DEPT_PALETTE[di % DEPT_PALETTE.length];
      for (var k = 0; k < list.length; k += maxCols) {
        rows.push({ dept: dName, color: color, items: list.slice(k, k + maxCols).map(function (it) { return { suspect: it, color: color, dept: dName }; }) });
      }
    }
    if (rows.length > 6) {
      var flat = [];
      for (var r = 0; r < rows.length; r += 1) flat = flat.concat(rows[r].items);
      var targetCols = Math.max(maxCols, Math.ceil(flat.length / 6));
      rows = [];
      for (var f = 0; f < flat.length; f += targetCols) {
        var sl = flat.slice(f, f + targetCols);
        rows.push({ dept: sl[0].dept, color: sl[0].color, items: sl });
      }
    }
    var rowCount = rows.length;
    var rowH = Math.floor(294 / rowCount);
    var stations = [];
    var rowBands = [];
    for (var ri = 0; ri < rowCount; ri += 1) {
      var row = rows[ri];
      var ry = 98 + ri * rowH;
      rowBands.push({ x: 14, y: ry + 2, w: 38, h: Math.max(24, rowH - 5), label: clipText(row.dept.toUpperCase(), 5), color: row.color });
      var colStep = Math.floor(648 / Math.max(row.items.length, Math.min(maxCols, total)));
      var cellW = Math.max(44, Math.min(112, colStep - 5));
      var cellH = Math.max(36, rowH - 5);
      for (var ci = 0; ci < row.items.length; ci += 1) {
        var entry = row.items[ci];
        stations.push({ x: 56 + ci * colStep, y: ry + 2, w: cellW, h: cellH, suspect: entry.suspect, deptColor: entry.color });
      }
    }
    return { stations: stations, rowBands: rowBands };
  }

  function resolveTrueMole(caseObj, evalResult) {
    if (caseObj && (caseObj.true_mole || caseObj.trueMole)) return String(caseObj.true_mole || caseObj.trueMole);
    if (evalResult && (evalResult.trueMole || evalResult.true_mole)) return String(evalResult.trueMole || evalResult.true_mole);
    return null;
  }

  function extractTopPosterior(caseObj, evalResult) {
    var solver = (caseObj && caseObj.solver) || (evalResult && evalResult.solver) || null;
    var post = solver && solver.posterior && typeof solver.posterior === "object" ? solver.posterior : {};
    return Object.keys(post)
      .map(function (id) { var val = Number(post[id]); return { id: id, prob: isFinite(val) && val > 0 ? val : 0 }; })
      .sort(function (a, b) { return b.prob !== a.prob ? b.prob - a.prob : (a.id < b.id ? -1 : 1); })
      .slice(0, 3);
  }

  function extractPodResults(caseObj, evalResult, trueMole) {
    var list = (evalResult && Array.isArray(evalResult.levelComparisons) && evalResult.levelComparisons.length ? evalResult.levelComparisons : null)
      || (evalResult && Array.isArray(evalResult.thinking_levels) ? evalResult.thinking_levels : null)
      || (caseObj && Array.isArray(caseObj.thinking_levels) ? caseObj.thinking_levels : null)
      || (caseObj && Array.isArray(caseObj.thinkingLevels) ? caseObj.thinkingLevels : []);
    var byLevel = {};
    for (var i = 0; i < list.length; i += 1) {
      var it = list[i] || {};
      var lv = String(it.thinking_level || it.thinkingLevel || it.level || it.key || "").toLowerCase();
      if (lv) byLevel[lv] = it;
    }
    var map = {};
    for (var p = 0; p < POD_LEVELS.length; p += 1) {
      var key = POD_LEVELS[p];
      var rec = byLevel[key] || null;
      var accused = rec ? (rec.accused || rec.final_accused || null) : null;
      var costNum = Number(rec ? (rec.cost_usd != null ? rec.cost_usd : rec.costUsd != null ? rec.costUsd : rec.cost) : 0);
      var correct = rec && typeof rec.correct === "boolean" ? rec.correct : Boolean(accused && trueMole && String(accused) === String(trueMole));
      map[key] = { accused: accused ? String(accused) : "HOLD", costUsd: isFinite(costNum) && costNum >= 0 ? costNum : 0, correct: correct };
    }
    return map;
  }

  function setSmoothOff(ctx) {
    if (!ctx) return;
    ctx.imageSmoothingEnabled = false;
    ctx.webkitImageSmoothingEnabled = false;
    ctx.mozImageSmoothingEnabled = false;
  }

  function create(containerEl, callbacks) {
    var cb = callbacks || {};
    var pods = POD_LEVELS.map(function (key, i) {
      return { key: key, label: POD_LABELS[key], color: POD_COLORS[key], x: 718, y: 98 + i * 82, w: 228, h: 76 };
    });
    var state = {
      caseObj: null, suspects: [], stations: [], rowBands: [],
      selectedSuspectId: null, highlightMap: {}, activeTab: "canaries",
      selectedPod: null, revealed: false, evalResult: null, revealStartMs: 0,
      hoverTarget: null, destroyed: false
    };
    var bank = loadSpriteBank(function () { paintNow(); });

    function hitTest(px, py) {
      for (var i = 0; i < state.stations.length; i += 1) {
        var st = state.stations[i];
        if (px >= st.x && px <= st.x + st.w && py >= st.y && py <= st.y + st.h) return { kind: "suspect", id: st.suspect.id };
      }
      for (var p = 0; p < PROPS.length; p += 1) {
        var pr = PROPS[p];
        if (px >= pr.x && px <= pr.x + pr.w && py >= pr.y && py <= pr.y + pr.h) return { kind: "tab", id: pr.key };
      }
      for (var k = 0; k < pods.length; k += 1) {
        var pd = pods[k];
        if (px >= pd.x && px <= pd.x + pd.w && py >= pd.y && py <= pd.y + pd.h) return { kind: "pod", id: pd.key };
      }
      return null;
    }

    function handleClickAt(px, py) {
      var hit = hitTest(px, py);
      if (!hit) return;
      if (hit.kind === "suspect") {
        state.selectedSuspectId = hit.id;
        paintNow();
        if (typeof cb.onSelectSuspect === "function") cb.onSelectSuspect(hit.id);
      } else if (hit.kind === "tab") {
        state.activeTab = hit.id;
        paintNow();
        if (typeof cb.onSelectTab === "function") cb.onSelectTab(hit.id);
      } else if (hit.kind === "pod") {
        state.selectedPod = hit.id;
        paintNow();
        if (typeof cb.onSelectThinkingPod === "function") cb.onSelectThinkingPod(hit.id);
      }
    }

    function renderScene(ctx, timeMs) {
      if (!ctx) return;
      setSmoothOff(ctx);
      var tick = Math.floor(timeMs / 16);
      for (var ty = 88; ty < GRID_H; ty += 32) {
        for (var tx = 0; tx < GRID_W; tx += 32) {
          if (!drawAsset(ctx, bank, "floor_tile", tx, ty, 32, 32, tick)) {
            fillBox(ctx, ((tx + ty) / 32) % 2 === 0 ? "#0f172a" : "#131c31", tx, ty, 32, 32);
            fillBox(ctx, "#1e293b", tx, ty, 32, 1);
          }
        }
      }
      for (var wx = 0; wx < GRID_W; wx += 32) {
        if (!drawAsset(ctx, bank, "wall_tile", wx, 0, 32, 88, tick)) {
          fillBox(ctx, "#172033", wx, 0, 32, 84);
          fillBox(ctx, "#293548", wx, 82, 32, 6);
        }
      }
      drawProp(ctx, bank, "door", 14, 18, 34, 66, tick);
      drawProp(ctx, bank, "window_night", 54, 16, 36, 52, tick);

      for (var p = 0; p < PROPS.length; p += 1) {
        var prop = PROPS[p];
        var isTabActive = state.activeTab === prop.key;
        var isPropHover = state.hoverTarget && state.hoverTarget.kind === "tab" && state.hoverTarget.id === prop.key;
        fillBox(ctx, isTabActive ? "#1e293b" : "#0b1120", prop.x, prop.y, prop.w, prop.h);
        strokeBox(ctx, isTabActive ? "#fbbf24" : isPropHover ? "#38bdf8" : "#334155", isTabActive ? 2 : 1, prop.x + 1, prop.y + 1, prop.w - 2, prop.h - 2);
        drawProp(ctx, bank, prop.sprite, prop.x + 34, prop.y + 6, 44, 42, tick);
        drawText(ctx, "[" + prop.label + "]", prop.x + prop.w / 2, prop.y + prop.h - 8, isTabActive ? "#fde047" : "#cbd5e1", "bold 10px monospace", "center");
      }

      fillBox(ctx, "#0b1120", 718, 10, 228, 74);
      strokeBox(ctx, state.revealed ? "#fbbf24" : "#38bdf8", 2, 719, 11, 226, 72);
      var caseTitle = state.caseObj ? (state.caseObj.title || state.caseObj.id || "ACTIVE CASE") : "OUT-THINK GEMINI";
      var tierLabel = state.caseObj ? String(state.caseObj.tier || "noir").toUpperCase() : "READY";
      drawText(ctx, clipText(caseTitle, 26), 728, 28, "#38bdf8", "bold 11px monospace");
      drawText(ctx, "TIER: " + tierLabel + " | SUSPECTS: " + state.suspects.length, 728, 46, "#94a3b8", "10px monospace");
      drawText(ctx, state.revealed ? "STATUS: CASE REVEALED" : "STATUS: PODS SEALED", 728, 66, state.revealed ? "#fde047" : "#64748b", "10px monospace");

      for (var rb = 0; rb < state.rowBands.length; rb += 1) {
        var band = state.rowBands[rb];
        fillBox(ctx, "#0b1120", band.x, band.y, band.w, band.h);
        fillBox(ctx, band.color, band.x, band.y, 4, band.h);
        drawText(ctx, band.label, band.x + 21, band.y + band.h / 2 + 3, band.color, "bold 9px monospace", "center");
      }

      var selectedStation = null;
      var moleId = state.revealed ? resolveTrueMole(state.caseObj, state.evalResult) : null;
      var moleStation = null;

      for (var si = 0; si < state.stations.length; si += 1) {
        var st = state.stations[si];
        var sus = st.suspect;
        var isSelected = state.selectedSuspectId === sus.id;
        var isHighlighted = Boolean(state.highlightMap[sus.id]);
        var isHover = state.hoverTarget && state.hoverTarget.kind === "suspect" && state.hoverTarget.id === sus.id;
        if (isSelected) selectedStation = st;
        if (moleId && sus.id === moleId) moleStation = st;

        ctx.save();
        if (sus.eliminated) ctx.globalAlpha = 0.36;
        fillBox(ctx, "#0f172a", st.x, st.y, st.w, st.h);
        fillBox(ctx, st.deptColor, st.x, st.y, st.w, 3);
        var cx = st.x + st.w / 2;
        drawProp(ctx, bank, "chair", cx - 9, st.y + 5, 18, 14, tick);
        drawActor(ctx, bank, sus.spriteKey, sus.variant, cx - 9, st.y + 6, 18, 20, tick, st.deptColor);
        drawProp(ctx, bank, "desk", st.x + 6, st.y + 22, st.w - 12, 12, tick);
        var tag = st.w >= 72 ? clipText(sus.id + " " + sus.shortName, 11) : clipText(sus.id, 6);
        drawText(ctx, tag, cx, st.y + st.h - 5, sus.eliminated ? "#94a3b8" : "#f8fafc", "bold 9px monospace", "center");
        if (sus.eliminated) {
          fillBox(ctx, "#475569", st.x + st.w - 22, st.y + 4, 20, 9);
          drawText(ctx, "CLR", st.x + st.w - 12, st.y + 11, "#e2e8f0", "8px monospace", "center");
        }
        ctx.restore();

        if (isHighlighted) {
          strokeBox(ctx, "#22d3ee", 2, st.x - 1, st.y - 1, st.w + 2, st.h + 2);
          strokeBox(ctx, "#fbbf24", 1, st.x + 1, st.y + 1, st.w - 2, st.h - 2);
        } else if (isHover) {
          strokeBox(ctx, "#94a3b8", 1, st.x, st.y, st.w, st.h);
        }
        if (isSelected) {
          var pulse = (Math.floor(tick / 10) % 2) * 2;
          var rx = st.x - 2 - pulse;
          var ry2 = st.y - 2 - pulse;
          var rw = st.w + 4 + pulse * 2;
          var rh = st.h + 4 + pulse * 2;
          ctx.strokeStyle = "#fde047";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(rx, ry2 + 8); ctx.lineTo(rx, ry2); ctx.lineTo(rx + 8, ry2);
          ctx.moveTo(rx + rw - 8, ry2); ctx.lineTo(rx + rw, ry2); ctx.lineTo(rx + rw, ry2 + 8);
          ctx.moveTo(rx, ry2 + rh - 8); ctx.lineTo(rx, ry2 + rh); ctx.lineTo(rx + 8, ry2 + rh);
          ctx.moveTo(rx + rw - 8, ry2 + rh); ctx.lineTo(rx + rw, ry2 + rh); ctx.lineTo(rx + rw, ry2 + rh - 8);
          ctx.stroke();
        }
      }

      if (state.revealed) {
        fillBox(ctx, "rgba(6, 10, 22, 0.42)", 12, 94, 696, 300);
        var targetX = moleStation ? moleStation.x + moleStation.w / 2 : 360;
        var targetY = moleStation ? moleStation.y + moleStation.h / 2 : 220;
        var ease = 1 - Math.pow(1 - Math.min(1, Math.max(0, timeMs - state.revealStartMs) / 700), 3);
        var spotX = Math.round(140 + (targetX - 140) * ease);
        var spotY = Math.round(390 + (targetY - 390) * ease);
        ctx.save();
        ctx.fillStyle = "rgba(251, 191, 36, 0.17)";
        ctx.beginPath();
        ctx.moveTo(132, 434); ctx.lineTo(spotX - 34, spotY); ctx.lineTo(spotX + 34, spotY);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = "rgba(254, 240, 138, 0.28)";
        ctx.beginPath();
        ctx.arc(spotX, spotY, 34, 0, Math.PI * 2);
        ctx.fill();
        strokeBox(ctx, "#ef4444", 2, spotX - 30, spotY - 24, 60, 48);
        fillBox(ctx, "#dc2626", spotX - 34, spotY - 36, 68, 12);
        drawText(ctx, "MOLE " + (moleId || "?"), spotX, spotY - 27, "#f8fafc", "bold 9px monospace", "center");
        ctx.restore();
      }

      if (selectedStation && !state.revealed) {
        var sbW = 216;
        var sbH = 30;
        var scx = selectedStation.x + selectedStation.w / 2;
        var sbX = Math.max(18, Math.min(704 - sbW, scx - sbW / 2));
        var placeBelow = selectedStation.y < 134;
        var sbY = placeBelow ? selectedStation.y + selectedStation.h + 7 : selectedStation.y - sbH - 7;
        fillBox(ctx, "#f8fafc", sbX, sbY, sbW, sbH);
        strokeBox(ctx, "#0f172a", 2, sbX, sbY, sbW, sbH);
        fillBox(ctx, "#f8fafc", scx - 4, placeBelow ? sbY - 5 : sbY + sbH, 8, 5);
        drawText(ctx, selectedStation.suspect.name + " [" + selectedStation.suspect.dept + "]", sbX + 6, sbY + 11, "#0f172a", "bold 9px monospace");
        drawText(ctx, clipText(selectedStation.suspect.quote, 32), sbX + 6, sbY + 23, "#334155", "9px monospace");
      }

      fillBox(ctx, "#0b1120", 14, 398, 236, 110);
      strokeBox(ctx, "#475569", 2, 15, 399, 234, 108);
      ctx.fillStyle = "rgba(251, 191, 36, 0.12)";
      ctx.beginPath();
      ctx.arc(116, 444, 42, 0, Math.PI * 2);
      ctx.fill();
      drawProp(ctx, bank, "chair", 52, 426, 26, 28, tick);
      drawActor(ctx, bank, "detective", "detective", 58, 418, 28, 34, tick, "#f59e0b");
      drawProp(ctx, bank, "desk", 34, 450, 110, 28, tick);
      drawProp(ctx, bank, "lamp", 116, 426, 20, 24, tick);
      drawText(ctx, "LEAD DETECTIVE", 150, 424, "#fbbf24", "bold 10px monospace");
      drawText(ctx, state.selectedSuspectId ? "FOCUS: " + state.selectedSuspectId : "SELECT A DESK", 150, 442, "#cbd5e1", "9px monospace");
      drawText(ctx, "TAB: " + state.activeTab.toUpperCase(), 150, 458, "#94a3b8", "9px monospace");
      drawText(ctx, "NOIR GRID 960x520", 34, 496, "#64748b", "9px monospace");

      fillBox(ctx, "#0b1120", 258, 398, 450, 110);
      strokeBox(ctx, state.revealed ? "#fbbf24" : "#334155", 2, 259, 399, 448, 108);
      if (state.revealed) {
        var top3 = extractTopPosterior(state.caseObj, state.evalResult);
        var verdictTxt = state.evalResult && state.evalResult.verdictLabel ? state.evalResult.verdictLabel : "TRUE MOLE: " + (moleId || "UNKNOWN");
        drawText(ctx, "SOLVER TOP-3 POSTERIOR | " + clipText(verdictTxt, 32), 270, 416, "#fde047", "bold 10px monospace");
        for (var bi = 0; bi < 3; bi += 1) {
          var rowY = 426 + bi * 24;
          var item = top3[bi] || { id: "--", prob: 0 };
          var pct = Math.max(0, Math.min(1, item.prob));
          var isTrue = moleId && item.id === moleId;
          drawText(ctx, (bi + 1) + ". " + clipText(item.id, 8), 270, rowY + 12, isTrue ? "#fde047" : "#e2e8f0", "bold 10px monospace");
          fillBox(ctx, "#1e293b", 348, rowY + 2, 276, 13);
          fillBox(ctx, isTrue ? "#22c55e" : "#38bdf8", 348, rowY + 2, 276 * pct, 13);
          drawText(ctx, (pct * 100).toFixed(1) + "%", 694, rowY + 12, "#f8fafc", "bold 10px monospace", "right");
        }
      } else {
        var line1 = selectedStation ? ("DOSSIER: " + selectedStation.suspect.name + " (" + selectedStation.suspect.id + ") | " + selectedStation.suspect.role) : "INVESTIGATION FLOOR BRIEFING";
        var line2 = selectedStation ? ("DEPT: " + selectedStation.suspect.dept + " | CANARY HITS: " + selectedStation.suspect.hits + " | AFTER-HOURS: " + selectedStation.suspect.afterHours) : "Click any suspect station to inspect alibi, canary hits, and chatter.";
        var line3 = selectedStation ? ("NOTE: " + clipText(selectedStation.suspect.quote, 52)) : "Click wall props for evidence tabs or inspect Gemini Thinking Pods.";
        drawText(ctx, line1, 270, 418, "#38bdf8", "bold 10px monospace");
        drawText(ctx, line2, 270, 440, "#cbd5e1", "10px monospace");
        drawText(ctx, line3, 270, 462, "#94a3b8", "10px monospace");
        drawText(ctx, "CYAN/GOLD = CANDIDATE FILTER   DIM = CLEARED   PODS UNLOCK ON REVEAL", 270, 492, "#22d3ee", "9px monospace");
      }

      var podMap = state.revealed ? extractPodResults(state.caseObj, state.evalResult, moleId) : {};
      for (var pi = 0; pi < pods.length; pi += 1) {
        var pod = pods[pi];
        var isPodSel = state.selectedPod === pod.key;
        var isPodHov = state.hoverTarget && state.hoverTarget.kind === "pod" && state.hoverTarget.id === pod.key;
        fillBox(ctx, "#0b1120", pod.x, pod.y, pod.w, pod.h);
        strokeBox(ctx, isPodSel ? "#fde047" : isPodHov ? "#38bdf8" : pod.color, isPodSel ? 2 : 1, pod.x + 1, pod.y + 1, pod.w - 2, pod.h - 2);
        var chamberKey = state.revealed ? "pod_unlocked" : "pod_locked";
        if (!drawAsset(ctx, bank, chamberKey, pod.x + 8, pod.y + 10, 40, 56, tick)) {
          fillBox(ctx, state.revealed ? "#0f2942" : "#1e293b", pod.x + 8, pod.y + 10, 40, 56);
          strokeBox(ctx, pod.color, 1, pod.x + 9, pod.y + 11, 38, 54);
        }
        if (!state.revealed) {
          fillBox(ctx, "rgba(14, 116, 144, 0.35)", pod.x + 12, pod.y + 16, 32, 44);
          drawText(ctx, "GEMINI " + pod.label, pod.x + 56, pod.y + 24, pod.color, "bold 11px monospace");
          ctx.save();
          ctx.globalAlpha = 0.45 + 0.45 * Math.abs(Math.sin(timeMs * 0.004 + pi * 0.7));
          drawText(ctx, "[LOCKED]", pod.x + 56, pod.y + 45, "#fbbf24", "bold 11px monospace");
          ctx.restore();
          drawText(ctx, "SEALED UNTIL CALL", pod.x + 56, pod.y + 62, "#64748b", "9px monospace");
        } else {
          drawActor(ctx, bank, "agent_" + pod.key, "agent", pod.x + 14, pod.y + 18, 28, 38, tick, pod.color);
          var res = podMap[pod.key] || { accused: "HOLD", costUsd: 0, correct: false };
          drawText(ctx, pod.label, pod.x + 54, pod.y + 20, pod.color, "bold 10px monospace");
          drawText(ctx, "ACC: " + clipText(res.accused, 9), pod.x + 54, pod.y + 40, "#f8fafc", "bold 10px monospace");
          drawText(ctx, "$" + res.costUsd.toFixed(4), pod.x + 54, pod.y + 58, "#94a3b8", "10px monospace");
          var iconKey = res.correct ? "icon_correct" : "icon_wrong";
          if (!drawAsset(ctx, bank, iconKey, pod.x + 158, pod.y + 12, 16, 16, tick)) {
            fillBox(ctx, res.correct ? "#16a34a" : "#dc2626", pod.x + 158, pod.y + 12, 16, 16);
            drawText(ctx, res.correct ? "V" : "X", pod.x + 166, pod.y + 24, "#f8fafc", "bold 10px monospace", "center");
          }
          fillBox(ctx, res.correct ? "#16a34a" : "#dc2626", pod.x + 154, pod.y + 34, 64, 20);
          drawText(ctx, res.correct ? "RIGHT" : "WRONG", pod.x + 186, pod.y + 48, "#f8fafc", "bold 10px monospace", "center");
        }
      }
    }

    var mode = "canvas2d";
    var canvas = null;
    var ctx2d = null;
    var rafId = null;
    var phaserGame = null;
    var phaserTex = null;
    var phaserCtx = null;
    var removeDomListeners = null;

    var PhaserLib = (typeof window !== "undefined" && window.Phaser) || (root && root.Phaser) || null;
    if (PhaserLib && typeof PhaserLib.Game === "function" && PhaserLib.CANVAS !== undefined && containerEl) {
      try {
        phaserGame = new PhaserLib.Game({
          type: PhaserLib.CANVAS, parent: containerEl, width: GRID_W, height: GRID_H,
          pixelArt: true, backgroundColor: "#0b1020", banner: false, audio: { noAudio: true },
          scene: {
            create: function () {
              phaserTex = this.textures.createCanvas("outthink_stage_" + Math.floor(nowMs()), GRID_W, GRID_H);
              phaserCtx = phaserTex.getContext();
              setSmoothOff(phaserCtx);
              this.add.image(GRID_W / 2, GRID_H / 2, phaserTex.key);
              this.input.on("pointermove", function (ptr) { state.hoverTarget = hitTest(ptr.x, ptr.y); });
              this.input.on("pointerdown", function (ptr) { handleClickAt(ptr.x, ptr.y); });
              renderScene(phaserCtx, nowMs());
              phaserTex.refresh();
            },
            update: function (time) {
              if (phaserCtx && phaserTex && !state.destroyed) {
                renderScene(phaserCtx, time || nowMs());
                phaserTex.refresh();
              }
            }
          }
        });
        if (phaserGame && phaserGame.canvas && phaserGame.canvas.style) {
          phaserGame.canvas.style.cssText = "width:100%;height:100%;display:block;image-rendering:pixelated;";
        }
        mode = "phaser";
      } catch (err) {
        phaserGame = null;
        mode = "canvas2d";
      }
    }

    if (mode === "canvas2d" && typeof document !== "undefined" && document.createElement) {
      canvas = document.createElement("canvas");
      canvas.width = GRID_W;
      canvas.height = GRID_H;
      if (canvas.style) {
        canvas.style.cssText = "width:100%;height:100%;display:block;image-rendering:pixelated;cursor:pointer;";
      }
      if (containerEl && typeof containerEl.appendChild === "function") containerEl.appendChild(canvas);
      if (typeof canvas.getContext === "function") {
        ctx2d = canvas.getContext("2d");
        setSmoothOff(ctx2d);
      }
      var toLogical = function (ev) {
        var rect = canvas.getBoundingClientRect ? canvas.getBoundingClientRect() : { left: 0, top: 0, width: GRID_W, height: GRID_H };
        return { x: ((ev.clientX - rect.left) * GRID_W) / (rect.width || GRID_W), y: ((ev.clientY - rect.top) * GRID_H) / (rect.height || GRID_H) };
      };
      var onMove = function (ev) {
        var pt = toLogical(ev);
        state.hoverTarget = hitTest(pt.x, pt.y);
        if (canvas && canvas.style) canvas.style.cursor = state.hoverTarget ? "pointer" : "default";
      };
      var onLeave = function () { state.hoverTarget = null; };
      var onClick = function (ev) { var pt = toLogical(ev); handleClickAt(pt.x, pt.y); };
      if (typeof canvas.addEventListener === "function") {
        canvas.addEventListener("mousemove", onMove);
        canvas.addEventListener("mouseleave", onLeave);
        canvas.addEventListener("click", onClick);
        removeDomListeners = function () {
          canvas.removeEventListener("mousemove", onMove);
          canvas.removeEventListener("mouseleave", onLeave);
          canvas.removeEventListener("click", onClick);
        };
      }
      var step = function (ts) {
        if (state.destroyed) return;
        renderScene(ctx2d, ts || nowMs());
        if (typeof requestAnimationFrame === "function") rafId = requestAnimationFrame(step);
      };
      renderScene(ctx2d, nowMs());
      if (typeof requestAnimationFrame === "function") rafId = requestAnimationFrame(step);
    }

    function paintNow() {
      if (state.destroyed) return;
      if (mode === "phaser" && phaserCtx && phaserTex) {
        renderScene(phaserCtx, nowMs());
        phaserTex.refresh();
      } else if (ctx2d) {
        renderScene(ctx2d, nowMs());
      }
    }

    function applyCase(caseObj, resetFilters) {
      if (Object.keys(bank).length === 0) bank = loadSpriteBank(function () { paintNow(); });
      state.caseObj = caseObj || null;
      state.suspects = extractSuspects(state.caseObj);
      var built = buildStations(state.suspects);
      state.stations = built.stations;
      state.rowBands = built.rowBands;
      if (resetFilters) {
        state.selectedSuspectId = null;
        state.highlightMap = {};
      }
    }

    return {
      mode: mode,
      setCase: function (caseObj) {
        applyCase(caseObj, true);
        state.revealed = false;
        state.evalResult = null;
        state.revealStartMs = 0;
        paintNow();
      },
      setSelectedSuspect: function (suspectId) {
        state.selectedSuspectId = suspectId ? String(suspectId) : null;
        paintNow();
      },
      setHighlightCandidates: function (idsArray) {
        var next = {};
        if (Array.isArray(idsArray)) {
          for (var i = 0; i < idsArray.length; i += 1) {
            if (idsArray[i] != null) next[String(idsArray[i])] = true;
          }
        }
        state.highlightMap = next;
        paintNow();
      },
      showReveal: function (evalResult, caseObj) {
        if (caseObj && typeof caseObj === "object" && caseObj !== state.caseObj) {
          applyCase(caseObj, false);
        }
        state.evalResult = evalResult || null;
        state.revealed = true;
        state.revealStartMs = nowMs();
        paintNow();
      },
      clearReveal: function () {
        state.revealed = false;
        state.evalResult = null;
        state.revealStartMs = 0;
        paintNow();
      },
      resize: function () {
        if (mode === "phaser" && phaserGame && phaserGame.scale && typeof phaserGame.scale.refresh === "function") {
          phaserGame.scale.refresh();
        }
        paintNow();
      },
      destroy: function () {
        state.destroyed = true;
        if (rafId !== null && typeof cancelAnimationFrame === "function") {
          cancelAnimationFrame(rafId);
          rafId = null;
        }
        if (typeof removeDomListeners === "function") {
          removeDomListeners();
          removeDomListeners = null;
        }
        if (phaserGame && typeof phaserGame.destroy === "function") {
          phaserGame.destroy(true);
          phaserGame = null;
        }
        if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
        canvas = null;
        ctx2d = null;
      }
    };
  }

  var OutThinkScene = { create: create };
  if (root) root.OutThinkScene = OutThinkScene;
  if (typeof window !== "undefined") window.OutThinkScene = OutThinkScene;
  if (typeof module !== "undefined" && module.exports) module.exports = OutThinkScene;
})(typeof window !== "undefined" ? window : typeof globalThis !== "undefined" ? globalThis : this);
