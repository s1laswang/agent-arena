(function () {
  const AD = window.AD, E = window.Eng;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const VC = { A: "#5bd1ff", B: "#ff8ad8", C: "#b6f06a" };
  const LBK = "canary-arena-lb-v1";
  const SEEDS = AD.index.seeds.map((s) => s.seed);
  const PATH_G = "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl";
  const PATH_S = "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl";
  const TOOLS = [
    ["status", "status", 1], ["list_employees", "list_employees", 1], ["list_documents", "list_documents", 1],
    ["read_access_logs", "read_access_logs", 0], ["search_messages", "search_messages", 0], ["read_message", "read_message", 0],
    ["interview", "interview", 0], ["plant_canary", "plant_canary", 0], ["check_leak_feed", "check_leak_feed", 0],
    ["restrict_access", "restrict_access", 0], ["unrestrict_access", "unrestrict_access", 0], ["advance_day", "advance_day", 1], ["accuse", "accuse", 1]
  ];
  const TDESC = {
    status: "V and actions", list_employees: "open the roster", list_documents: "who holds what", read_access_logs: "who opened what",
    search_messages: "keyword search", read_message: "open one message", interview: "ask one person", plant_canary: "fake doc, variants",
    check_leak_feed: "what surfaced", restrict_access: "cut off a person", unrestrict_access: "undo that", advance_day: "end the day", accuse: "ends the game"
  };

  let office, S = { mode: null }, timers = [], raf = 0, last = 0;

  function lbLoad() { try { return JSON.parse(localStorage.getItem(LBK)) || []; } catch (e) { return []; } }
  function lbAdd(x) {
    try {
      const a = lbLoad();
      a.push(x);
      a.sort((p, q) => q.score - p.score);
      localStorage.setItem(LBK, JSON.stringify(a.slice(0, 60)));
    } catch (e) {}
  }
  function toast(msg, cls) {
    const d = document.createElement("div");
    d.className = "toast " + (cls || "");
    d.textContent = msg;
    $("toasts").appendChild(d);
    setTimeout(() => d.remove(), 3200);
  }
  function later(f, ms) { const t = setTimeout(f, ms); timers.push(t); return t; }
  function clearTimers() { timers.forEach((t) => { clearTimeout(t); clearInterval(t); }); timers = []; }

  function bird() {
    const m = ["....yyyy..", "...yyyyyy.", "..yyyykyyy", "..yyyyyyoo", "..yyyyyy..", ".yyyyyyyy.", "yyyyyyyyy.", ".yyyyyyy..", "...o..o..."];
    const c = document.createElement("canvas");
    c.width = 10; c.height = 9;
    c.className = "bird";
    c.style.width = "80px";
    const g = c.getContext("2d");
    m.forEach((row, y) => [...row].forEach((ch, x) => {
      if (ch === ".") return;
      g.fillStyle = ch === "y" ? "#ffd23f" : ch === "k" ? "#111" : "#ff9a3c";
      g.fillRect(x, y, 1, 1);
    }));
    return c;
  }

  function showScreen(html, birdOn) {
    const s = $("screen");
    s.innerHTML = '<div class="card">' + html + "</div>";
    s.classList.remove("hide");
    s.classList.remove("ttl");
    if (birdOn) { const b = s.querySelector(".card"); b.insertBefore(bird(), b.firstChild); }
    s.scrollTop = 0;
  }
  function hideScreen() { $("screen").classList.add("hide"); }

  function toTitle() {
    clearTimers();
    S = { mode: null };
    $("hud").classList.add("hide");
    $("menuBtn").classList.add("hide");
    $("modeChip").textContent = "menu";
    $("banner").classList.add("hide");
    $("tools").innerHTML = "";
    $("side").innerHTML = "";
    const w = AD.world[SEEDS[Math.floor(Math.random() * SEEDS.length)]];
    office.setEmployees(w.employees, w.depts);
    office.setNight(false, true);
    office.onSelect = null;
    office.avoid = null;
    showScreen(
      '<div class="title">CANARY ARENA</div><div class="sub">Find the mole.</div>' +
      '<div class="modes">' +
      '<button class="mode pri" data-go="solver" style="grid-column:1/-1"><h3>OUR SOLVER vs GEMINI</h3><p>Same office. Watch both hunt.</p></button>' +
      '<button class="mode pri" data-go="easy"><h3>PLAY: FIND THE MOLE</h3><p>3 buttons a day. Under 2 minutes.</p></button>' +
      '<button class="mode" data-go="walk"><h3>WALK THE OFFICE</h3><p>Optional. Talk. Print traps. Name him.</p></button>' +
      '<button class="mode" data-go="duel"><h3>DUEL VS GEMINI</h3><p>Same office. Beat the AI.</p></button>' +
      '<button class="mode" data-go="mole"><h3>BE THE MOLE</h3><p>Leak. Do not get caught.</p></button>' +
      '</div><div class="row" style="justify-content:center"><button class="big" data-go="how">HOW?</button><button class="big" data-go="lb">SCORES</button></div>',
      true
    );
    $("screen").classList.add("ttl");
  }

  function howScreen() {
    showScreen(
      '<h2 class="yl">HOW</h2><div class="how">' +
      "<p>1 of 40 staff is the mole.</p><p>Every leak costs money. Every trap too.</p>" +
      "<p>Give each person a different copy of a paper. The leaked copy names the group.</p>" +
      "<p>Right accuse: you score the money left. Wrong: -1. None: 0.</p></div>" +
      '<div class="row"><button class="pri big" data-go="title">BACK</button></div>'
    );
  }

  function lbScreen(mode) {
    mode = mode || "duel";
    const all = lbLoad().filter((x) => x.mode === mode).slice(0, 12);
    showScreen(
      '<h2 class="yl">LEADERBOARD</h2><div class="tabs" style="margin-top:10px">' +
      ["duel", "mole"].map((m) => '<button class="' + (m === mode ? "on" : "") + '" data-lb="' + m + '">' + m + "</button>").join("") + "</div>" +
      (all.length ? "<table><tr><th>#</th><th>name</th><th>score</th><th>seed</th><th>note</th></tr>" +
        all.map((x, i) => "<tr><td>" + (i + 1) + "</td><td>" + esc(x.name) + '</td><td class="yl">' + x.score + "</td><td>" + (x.seed == null ? "" : x.seed) + "</td><td class='mu'>" + esc(x.note || "") + "</td></tr>").join("") + "</table>" : '<p class="mu">Nothing here yet. Be the first.</p>') +
      '<div class="row" style="margin-top:12px"><button class="pri big" data-go="' + (S.mode ? "close" : "title") + '">BACK</button></div>'
    );
  }

  function seedScreen() {
    showScreen(
      '<h2 class="yl">PICK A SEED</h2>' +
      '<div class="seedrow">' + SEEDS.map((s) => '<button class="big" data-seed="' + s + '">' + s + "</button>").join("") + "</div>" +
      '<div class="row" style="justify-content:center"><button class="pri big" data-seed="rand">RANDOM</button><button class="big" data-go="title">BACK</button></div>'
    );
  }

  function resetStage() {
    clearTimers();
    office.clearMarks();
    office.floaters = [];
    office.parts = [];
    office.stay.clear();
    office.avoid = null;
    office.onSelect = null;
    $("hud").classList.remove("hide");
    $("menuBtn").classList.remove("hide");
  }

  function hud() {
    const env = S.env;
    if (!env) return;
    $("dayN").textContent = Math.min(21, env.day);
    $("vfill").style.width = Math.max(0, env.V * 100) + "%";
    $("vnum").textContent = env.V.toFixed(2);
    $("pips").innerHTML = [...Array(8)].map((_, i) => "<b" + (i >= env.actions ? ' class="off"' : "") + "></b>").join("");
  }

  function nightCycle(cb) {
    S.busy = true;
    office.setNight(true);
    later(() => {
      office.setNight(false);
      S.busy = false;
      if (cb) cb();
    }, 2300);
  }

  function nm(id) { const e = S.emp && S.emp[id]; return e ? e.name : id; }
  function who(id) { return id + " " + nm(id).split(" ")[0]; }

  function evidenceMap() { return S.env.evidence(); }
  function applyMarks() {
    office.badges = {};
    office.rings = {};
    office.dim = new Set();
    const env = S.env;
    if (S.mode === "duel") {
      env.restricted.forEach((id) => { office.rings[id] = "#ff5a5a"; office.dim.add(id); });
      if (S.comp) Object.keys(S.comp.asg).forEach((id) => (office.badges[id] = { text: S.comp.asg[id], color: VC[S.comp.asg[id]] }));
      else if (S.heat) {
        const ev = evidenceMap(), mx = Math.max.apply(null, Object.values(ev));
        if (mx > 0) Object.keys(ev).forEach((id) => {
          if (ev[id] === mx) office.badges[id] = { text: String(ev[id]), color: "#ff6b6b" };
          else if (ev[id] > 0) office.badges[id] = { text: String(ev[id]), color: "#ffc247" };
        });
      }
      if (S.hold) S.hold.forEach((id) => (office.rings[id] = "#4aa3ff"));
    }
    office.selected = S.sel;
  }

  function startDuel(seed) {
    resetStage();
    hideScreen();
    const world = AD.world[seed];
    S = { mode: "duel", seed, world, env: new E.Env(world, seed), emp: {}, sel: null, tab: "tools", form: null, res: null, log: [], comp: null, heat: false, hold: null, busy: false, gem: AD.gem[seed], gemShown: 0, over: false, started: Date.now() };
    world.employees.forEach((e) => (S.emp[e.id] = e));
    $("modeChip").textContent = "duel seed " + seed;
    office.setEmployees(world.employees, world.depts);
    office.setNight(false, true);
    office.onSelect = (id) => {
      if (S.over) return;
      if (S.comp) { cycleVariant(id); return; }
      S.sel = id;
      office.pulse(id, "#ffd23f");
      applyMarks();
      renderTools();
    };
    const b = $("banner");
    b.classList.remove("hide");
    b.textContent = "Click an employee to select";
    S.gemTimer = setInterval(gemTick, 130);
    timers.push(S.gemTimer);
    gemTarget();
    hud();
    renderTools();
    renderSide();
  }

  function gemTarget() {
    const g = S.gem;
    const day = S.env.over && S.env.day > 21 ? 99 : S.env.day;
    S.gemWant = g.steps.filter((s) => s.day <= day).length;
    if (S.over) S.gemWant = g.steps.length;
  }
  function gemTick() {
    if (!S || S.mode !== "duel") return;
    if (S.gemShown < S.gemWant) {
      S.gemShown++;
      renderSide(true);
    }
  }

  function stepText(s) {
    const a = s.args || {}, r = s.result || {}, d = r.data || {};
    if (!r.ok) return '<span class="rd">error</span> ' + esc(String((r.error || "").slice(0, 60)));
    switch (s.tool) {
      case "status": return "V " + d.V + ", " + d.actions_left_today + " actions left";
      case "list_employees": return "40 employees";
      case "list_documents": return (d.documents || []).length + " documents, days " + a.day_from + " to " + a.day_to;
      case "read_access_logs": return (d.logs || []).length + " log lines, days " + a.day_from + " to " + a.day_to;
      case "search_messages": return 'query "' + esc(a.query) + '" gave ' + (d.messages || []).length;
      case "read_message": return "read " + esc(a.id);
      case "interview": return who(a.employee) + " on " + a.topic.replace("_", " ") + ": <span class='mu'>" + esc((d.answer || "").slice(0, 70)) + "</span>";
      case "plant_canary": {
        const n = Object.keys(a.assignment || {}).length, v = new Set(Object.values(a.assignment || {})).size;
        return "planted <b>" + esc(a.doc_title) + "</b> to " + n + " people in " + v + " versions";
      }
      case "check_leak_feed": return (d.items || []).length ? (d.items || []).map((i) => esc(i.title) + (i.variant ? " [" + i.variant + "]" : "")).join("; ") : "empty feed";
      case "restrict_access": return "restricted " + who(a.employee);
      case "unrestrict_access": return "unrestricted " + who(a.employee);
      case "advance_day": return "day " + d.closed_day + " ends, V " + d.V;
      case "accuse": return S.over ? "<b class='yl'>ACCUSED " + who(a.employee) + "</b>" : "<b class='yl'>ACCUSATION MADE, sealed until you finish</b>";
      default: return "";
    }
  }

  function renderSide(keep) {
    const el = $("side");
    if (S.mode === "duel") {
      const g = S.gem, shown = g.steps.slice(0, S.gemShown);
      let html = '<h3 class="yl">GEMINI 4 CARBON</h3><div class="mu" style="font-size:11px;margin-bottom:6px">Real committed run on seed ' + S.seed + ". It moves as you move: its day N appears when you reach day N.</div>";
      html += '<div class="row"><span class="chip">steps ' + S.gemShown + "/" + g.steps.length + '</span><span class="chip">its last day: ' + g.final_day + "</span></div>";
      html += '<div class="gem" id="gemList">';
      let cd = 0;
      shown.forEach((s) => {
        if (s.day !== cd) { cd = s.day; html += '<div class="gday">GEMINI DAY ' + cd + "</div>"; }
        const col = s.tool === "accuse" ? "var(--yl)" : s.tool === "plant_canary" ? "var(--bl)" : s.tool === "interview" ? "var(--pu)" : "var(--ln)";
        html += '<div class="gstep' + (s.result.ok ? "" : " err") + '" style="border-left-color:' + col + '"><span class="mu">' + s.tool + "</span> " + stepText(s) + "</div>";
      });
      if (S.gemShown >= g.steps.length) html += '<div class="gstep" style="border-color:var(--yl)">Gemini is done. Verdict is revealed at the end screen.</div>';
      html += "</div>";
      el.innerHTML = html;
      const l = $("gemList");
      if (l) l.scrollTop = l.scrollHeight;
    } else if (S.mode === "mole") renderMoleSide();
    else if (S.mode === "living") renderLivingSide();
  }

  function renderTools() {
    if (S.mode === "duel") renderDuelTools();
    else if (S.mode === "mole") renderMoleTools();
    else if (S.mode === "living") renderLivingTools();
  }

  function selChip() {
    return S.sel ? '<span class="chip" style="color:var(--yl)">selected ' + esc(S.sel) + " " + esc(nm(S.sel)) + "</span>" : '<span class="chip">nobody selected</span>';
  }

  function renderDuelTools() {
    const env = S.env, el = $("tools");
    const tabs = ["tools", "roster", "case", "log"].map((t) => '<button class="' + (S.tab === t ? "on" : "") + '" data-tab="' + t + '">' + t + "</button>").join("");
    let html = '<div class="tabs">' + tabs + '<span style="flex:1"></span>' + selChip() + "</div>";
    if (S.tab === "tools") {
      html += '<div class="grid">' + TOOLS.map((t) => '<button data-tool="' + t[0] + '" class="' + (t[2] ? "free" : "") + '"' + (S.over || S.busy ? " disabled" : "") + ">" + t[1] + "<small>" + (t[2] ? "free, " : "1 action, ") + TDESC[t[0]] + "</small></button>").join("") + "</div>";
      html += formHtml();
      if (S.res) html += '<div class="res">' + S.res + "</div>";
    } else if (S.tab === "roster") html += rosterHtml();
    else if (S.tab === "case") html += caseHtml();
    else html += logHtml();
    el.innerHTML = html;
    const inp = el.querySelector("#qin");
    if (inp && S.form && S.form.focus) { inp.focus(); S.form.focus = false; }
    hud();
    applyMarks();
  }

  function formHtml() {
    const f = S.form;
    if (!f) return "";
    const d = S.env.day;
    if (f.type === "logs") {
      return '<div class="row"><span class="mu">days:</span><button data-logs="' + Math.max(1, d - 1) + "," + Math.max(1, d - 1) + '">yesterday</button><button data-logs="' + Math.max(1, d - 3) + "," + (d - 1) + '">last 3</button><button data-logs="1,' + (d - 1) + '">all</button><button data-togf class="' + (f.only ? "on" : "") + '">only selected</button></div>';
    }
    if (f.type === "docs") {
      return '<div class="row"><span class="mu">days:</span><button data-docs="' + d + "," + d + '">today</button><button data-docs="' + Math.max(1, d - 2) + "," + d + '">last 3</button><button data-docs="1,' + d + '">all</button></div>';
    }
    if (f.type === "search") {
      return '<div class="row"><input id="qin" type="text" placeholder="keyword, e.g. proposal" value="' + esc(f.q || "") + '" style="flex:1"><button class="pri" data-search>Search</button></div>';
    }
    if (f.type === "interview") {
      return '<div class="row"><span class="mu">ask ' + esc(S.sel || "?") + ":</span>" + E.TOPICS.map((t) => '<button data-iv="' + t + '">' + t + "</button>").join("") + "</div>";
    }
    if (f.type === "compose") return composeHtml();
    return "";
  }

  function composeHtml() {
    const c = S.comp, cnt = { A: 0, B: 0, C: 0 };
    Object.values(c.asg).forEach((v) => cnt[v]++);
    let h = '<div class="row"><input id="ctitle" type="text" value="' + esc(c.title) + '" maxlength="60" style="flex:1"></div>';
    h += '<div class="row"><span class="mu">click employees (here or on the map) to cycle A, B, C, none</span></div>';
    h += '<div class="row"><button data-split="2">split all in 2</button><button data-split="3">split all in 3</button><button data-split="top">split top suspects in 3</button><button data-split="0">clear</button></div>';
    h += '<div class="row">' + ["A", "B", "C"].map((v) => '<span class="tag" style="background:' + VC[v] + '">' + v + " " + cnt[v] + "</span>").join(" ") + ' <button class="pri" data-plant>Plant canary (-0.01)</button><button data-cancel>Cancel</button></div>';
    h += '<div class="rost" style="max-height:170px">' + S.world.employees.map((e) => {
      const v = c.asg[e.id];
      return '<div class="emp" data-cyc="' + e.id + '"><span class="tag" style="background:' + (v ? VC[v] : "#2a3144") + ';color:' + (v ? "#10151f" : "#8b97b3") + '">' + (v || "-") + "</span>" + esc(e.id) + " " + esc(e.name) + "</div>";
    }).join("") + "</div>";
    return h;
  }

  function rosterHtml() {
    const ev = evidenceMap(), mx = Math.max(1, Math.max.apply(null, Object.values(ev)));
    return '<div class="rost">' + S.world.employees.map((e) => {
      const di = S.world.depts.indexOf(e.dept);
      return '<div class="emp ' + (S.sel === e.id ? "sel" : "") + '" data-pick="' + e.id + '"><span class="dot" style="background:' + window.DEPT_COL[di] + '"></span><span style="flex:1;min-width:0">' + esc(e.id) + " " + esc(e.name) + '<br><span class="mu" style="font-size:10px">' + esc(e.dept) + ", " + esc(e.role) + ", L" + e.clearance + (S.env.restricted.has(e.id) ? ' <b class="rd">restricted</b>' : "") + '</span></span><span class="heat"><i style="width:' + (ev[e.id] / mx) * 100 + '%"></i></span></div>';
    }).join("") + "</div>";
  }

  function caseHtml() {
    const env = S.env, ev = evidenceMap();
    let h = '<div class="row"><button data-heatt class="' + (S.heat ? "on" : "") + '">show evidence on map</button></div>';
    const feed = env.feed();
    h += "<h3 class='yl' style='margin:6px 0'>LEAKS SURFACED</h3>";
    h += feed.length ? feed.map((f) => {
      const doc = env.docs.find((d) => d.doc_id === f.doc_id);
      let set = doc.recipients;
      if (f.variant) set = env.canaries.find((c) => c.id === f.doc_id).variants[f.variant] || [];
      return '<div class="l">day ' + f.surfaced_day + ": <b>" + esc(f.title) + "</b> " + (f.variant ? '<span class="tag" style="background:' + VC[f.variant] + '">' + f.variant + "</span>" : '<span class="mu">no variant</span>') + ' <button data-hold="' + set.join(",") + '" style="padding:0 6px">' + set.length + " holders</button></div>";
    }).join("") : '<div class="mu">None yet. Leaks surface 2 to 3 days after they happen.</div>';
    h += "<h3 class='yl' style='margin:8px 0 4px'>CANARIES</h3>";
    h += env.canaries.length ? env.canaries.map((c) => '<div class="l">' + c.id + " day " + c.day + " <b>" + esc(c.title) + "</b><br>" + Object.keys(c.variants).sort().map((v) => '<button data-hold="' + c.variants[v].join(",") + '" style="padding:0 6px;border-color:' + VC[v] + '">' + v + " " + c.variants[v].length + "</button>").join(" ") + "</div>").join("") : '<div class="mu">No canaries yet.</div>';
    h += "<h3 class='yl' style='margin:8px 0 4px'>TOP SUSPECTS BY EVIDENCE</h3>";
    const top = Object.keys(ev).sort((a, b) => ev[b] - ev[a]).slice(0, 8);
    h += top.filter((i) => ev[i] > 0).length ? top.filter((i) => ev[i] > 0).map((i) => '<div class="emp" data-pick="' + i + '">' + esc(i) + " " + esc(nm(i)) + ' <span class="yl">' + ev[i] + " hits</span></div>").join("") : '<div class="mu">Nobody stands out yet.</div>';
    return h;
  }

  function logHtml() {
    return '<div class="res" style="max-height:340px">' + (S.log.length ? S.log.slice().reverse().map((l) => '<div class="l"><span class="mu">d' + l.day + "</span> <b>" + l.tool + "</b> " + esc(JSON.stringify(l.args).slice(0, 80)) + (l.ok ? "" : ' <span class="rd">' + esc(l.err) + "</span>") + "</div>").join("") : '<span class="mu">no calls yet</span>') + "</div>";
  }

  function cycleVariant(id) {
    const c = S.comp, v = c.asg[id], o = [undefined, "A", "B", "C"], i = o.indexOf(v);
    const n = o[(i + 1) % 4];
    if (n) c.asg[id] = n; else delete c.asg[id];
    office.pulse(id, n ? VC[n] : "#666");
    renderTools();
  }

  function act(tool, args) {
    const env = S.env, r = env.call(tool, args);
    S.log.push({ day: env.day, tool, args: args || {}, ok: r.ok, err: r.error });
    if (!r.ok) toast(String(r.error), "bad");
    return r;
  }

  function renderResult(tool, r, a) {
    const d = r.data || {};
    if (!r.ok) return '<span class="rd">' + esc(String(r.error)) + "</span>";
    switch (tool) {
      case "status": return "Day " + d.day + ", V " + d.V + ", actions left " + d.actions_left_today + ", calls left " + d.tool_calls_left + "<br>restricted: " + (d.restricted.length ? d.restricted.join(", ") : "none") + "<br>canaries: " + (d.canaries_planted.join(", ") || "none");
      case "list_documents": return (d.documents || []).map((x) => '<div class="l"><span class="mu">' + x.doc_id + " d" + x.day + "</span> " + esc(x.title) + (x.is_canary ? ' <span class="yl">canary</span>' : "") + ' <button data-hold="' + x.recipients.join(",") + '" style="padding:0 6px">' + x.recipients.length + " holders</button></div>").join("") || "no documents";
      case "read_access_logs": {
        const ah = {}, tot = {};
        d.logs.forEach((l) => { tot[l.employee] = (tot[l.employee] || 0) + 1; if (l.after_hours) ah[l.employee] = (ah[l.employee] || 0) + 1; });
        const top = Object.keys(ah).sort((x, y) => ah[y] - ah[x]).slice(0, 8);
        return d.logs.length + " accesses. After-hours leaders (noisy, the decoy and framing add fakes):" + (top.length ? top.map((i) => '<div class="emp" data-pick="' + i + '">' + esc(i) + " " + esc(nm(i)) + ' <span class="yl">' + ah[i] + " after-hours of " + tot[i] + "</span></div>").join("") : " none");
      }
      case "search_messages": return (d.messages || []).map((m) => '<div class="l"><span class="mu">' + m.id + " d" + m.day + " " + m.channel + "</span> " + esc(who(m.sender)) + ": <b>" + esc(m.subject) + '</b> <button data-rm="' + m.id + '" style="padding:0 6px">read</button><br><span class="mu">' + esc(m.snippet) + "</span></div>").join("") || "no results";
      case "read_message": return "<b>" + esc(d.message.subject) + "</b> from " + esc(who(d.message.sender)) + "<br>" + esc(d.message.body);
      case "interview": return "<b>" + esc(who(d.employee)) + "</b> (" + d.topic.replace("_", " ") + '): <span class="' + (d.evasive ? "rd" : "gn") + '">' + (d.evasive ? "[evasive] " : "") + esc(d.answer) + "</span>";
      case "check_leak_feed": return (d.items || []).map((i) => "day " + i.surfaced_day + ": <b>" + esc(i.title) + "</b> " + (i.variant ? '<span class="tag" style="background:' + VC[i.variant] + '">' + i.variant + "</span>" : "<span class='mu'>no variant</span>")).join("<br>") || "feed is empty";
      case "restrict_access": case "unrestrict_access": return "restricted now: " + (d.restricted.join(", ") || "none");
      default: return "ok";
    }
  }

  function onTool(t) {
    if (S.busy || S.over) return;
    const env = S.env, need = () => { if (!S.sel) { toast("Click an employee first", "bad"); return false; } return true; };
    S.form = null;
    S.hold = null;
    if (t === "status") { const r = act(t); S.res = renderResult(t, r); }
    else if (t === "list_employees") { act(t); S.tab = "roster"; }
    else if (t === "list_documents") { S.form = { type: "docs" }; const r = act(t, { day_from: Math.max(1, env.day - 2), day_to: env.day }); S.res = renderResult(t, r); }
    else if (t === "read_access_logs") { if (env.day < 2) { toast("Logs exist for ended days only", "bad"); } else S.form = { type: "logs", only: false }; }
    else if (t === "search_messages") S.form = { type: "search", focus: true };
    else if (t === "read_message") toast("Search first, then press read on a message", "");
    else if (t === "interview") { if (need()) S.form = { type: "interview" }; }
    else if (t === "plant_canary") {
      if (env.plantedToday >= 2) toast("2 canaries per day maximum", "bad");
      else { S.comp = { title: "Q" + env.day + " Strategy Note " + (env.plantedToday + 1), asg: {} }; S.form = { type: "compose" }; }
    }
    else if (t === "check_leak_feed") { const r = act(t); S.res = renderResult(t, r); if (r.ok && r.data.items.length) S.res += ""; }
    else if (t === "restrict_access" || t === "unrestrict_access") {
      if (need()) { const r = act(t, { employee: S.sel }); S.res = renderResult(t, r); if (r.ok) office.pulse(S.sel, t === "restrict_access" ? "#ff5a5a" : "#4fd6a0"); }
    }
    else if (t === "advance_day") return doAdvance();
    else if (t === "accuse") { if (need()) return confirmAccuse(); }
    renderTools();
  }

  function doAdvance() {
    const env = S.env;
    if (env.day >= 21) toast("Last day. Advancing ends the game with score 0 unless you accuse", "bad");
    const r = act("advance_day");
    S.form = null;
    S.comp = null;
    S.res = null;
    S.hold = null;
    S.tab = "tools";
    if (!r.ok) return;
    const ev = env.events[env.events.length - 1];
    nightCycle(() => {
      if (env.over) return finishDuel();
      gemTarget();
      toast("Day " + env.day + " begins. " + (r.data.new_documents || []).length + " new documents", "");
      if (ev.surfaced.length) {
        office.shake = 7;
        ev.surfaced.forEach((l) => { toast("LEAK SURFACED: " + l.title + (l.variant ? " (version " + l.variant + ")" : ""), "bad"); office.floatAt(352, 20 + Math.random() * 30, "-0.05", "#ff5a5a"); });
      }
      renderTools();
      renderSide();
      hud();
    });
    renderTools();
  }

  function confirmAccuse() {
    const e = S.emp[S.sel];
    showScreen('<h2 class="rd">ACCUSE ' + esc(e.name) + "?</h2><p>" + esc(e.id) + ", " + esc(e.dept) + ", " + esc(e.role) + ". If you are wrong the score is -1. If right, you score V = " + S.env.V.toFixed(2) + " and the game ends.</p>" +
      '<div class="row"><button class="dng" data-accuse="' + e.id + '">Accuse</button><button data-go="close">Keep investigating</button></div>');
  }

  function finishDuel() {
    S.over = true;
    const env = S.env, w = S.world, mole = w.mole;
    S.gemShown = S.gem.steps.length;
    S.gemWant = S.gemShown;
    S.heat = false;
    office.clearMarks();
    office.rings[mole] = "#ff5a5a";
    office.badges[mole] = { text: "MOLE", color: "#ff5a5a" };
    const e = office.byId[mole];
    if (e) office.burst(e.x * 16 + 8, e.y * 16 + 8, "#ff5a5a", 30);
    renderSide();
    renderTools();
    const acc = env.accused;
    later(() => endDuel(), 1400);
    S.accused = acc;
  }

  function endDuel() {
    const env = S.env, w = S.world, row = AD.index.seeds.find((x) => x.seed === S.seed), you = env.score, g = row.gemini, sv = row.solver;
    const arr = [["YOU", you, S.accused, S.accused === w.mole, env.day > 21 ? 21 : env.day, S.accused ? "accused" : "no accusation"], ["GEMINI", g.score, g.accused, g.correct, g.final_day, g.end_reason], ["SOLVER", sv.score, sv.accused, sv.correct, sv.final_day, sv.end_reason]];
    const best = Math.max(you, g.score, sv.score);
    const caught = arr.filter((x) => x[3]).map((x) => x[0]);
    const headline = you > g.score ? "YOU BEAT GEMINI" : you === g.score ? "TIE WITH GEMINI" : "GEMINI WINS THIS ONE";
    const card = (x) => '<div class="' + (x[1] === best ? "win" : "") + '"><div class="mu">' + x[0] + '</div><div class="big ' + (x[1] < 0 ? "rd" : x[1] === best ? "gn" : "yl") + '">' + x[1].toFixed(2) + "</div><div>" + (x[2] ? (x[3] ? '<b class="gn">caught the mole</b>' : '<b class="rd">accused ' + esc(x[2]) + ", wrong</b>") : "never accused") + '</div><div class="mu" style="font-size:11px">day ' + x[4] + ", " + esc(x[5]) + "</div></div>";
    const me = w.employees.find((e) => e.id === w.mole);
    showScreen('<div class="title" style="font-size:clamp(22px,4.5vw,40px)">' + headline + "</div>" +
      '<p class="sub">The mole was <b class="rd">' + esc(me.id + " " + me.name) + "</b>, " + esc(me.dept) + ", " + esc(me.role) + ". Who caught them: " + (caught.length ? caught.join(", ") : "nobody") + ".</p>" +
      '<div class="cmp">' + arr.map(card).join("") + "</div>" +
      '<div class="row" style="justify-content:center"><input id="pname" type="text" maxlength="14" placeholder="your name" value="' + esc(localStorage.getItem("canary-name") || "") + '"><button class="pri" data-save>Save to leaderboard</button></div>' +
      '<div class="row" style="justify-content:center"><button data-again>Same seed again</button><button data-go="duel">New seed</button><button data-go="title">Menu</button><button data-go="close">Look at the office</button></div>' +
      '<div class="src">Sources shown on screen: ' + AD.index.source.map(esc).join(" ; ") + "<br>Gemini score and accusation from " + PATH_G + "<br>Solver score from " + PATH_S + "<br>Seed " + S.seed + " is a " + esc(row.group) + " seed for Gemini.</div>");
    S.lastResult = { mode: "duel", score: you, seed: S.seed, note: (S.accused === w.mole ? "caught" : S.accused ? "wrong" : "none") + " vs gemini " + g.score.toFixed(2) };
  }

  function saveScore() {
    const n = ($("pname") && $("pname").value.trim()) || "anon";
    try { localStorage.setItem("canary-name", n); } catch (e) {}
    lbAdd(Object.assign({ name: n, ts: Date.now() }, S.lastResult));
    toast("Saved to leaderboard", "good");
    lbScreen(S.lastResult.mode);
  }

  function startMole() {
    resetStage();
    hideScreen();
    const seed = SEEDS[Math.floor(Math.random() * SEEDS.length)];
    const world = AD.world[seed];
    const ids = world.employees.map((e) => e.id);
    const pid = ids[Math.floor(Math.random() * ids.length)];
    const w2 = Object.assign({}, world, { mole: pid, decoy: world.decoy === pid ? ids[(ids.indexOf(pid) + 1) % 40] : world.decoy });
    const env = new E.Env(w2, seed * 7 + 1);
    env.moleControl = true;
    const hunter = new E.Hunter(env, seed);
    hunter.plant(1);
    S = { mode: "mole", seed, world: w2, env, hunter, pid, emp: {}, pick: null, hlog: ["Day 1: hunter plants 2 canary documents and splits all 40 employees. You cannot tell which of your documents are canaries."], busy: false, over: false, leaksMade: 0 };
    world.employees.forEach((e) => (S.emp[e.id] = e));
    $("modeChip").textContent = "be the mole";
    office.setEmployees(world.employees, world.depts);
    office.setNight(false, true);
    moleMarks();
    const b = $("banner");
    b.classList.remove("hide");
    b.textContent = "You are " + S.emp[pid].name + " (gold marker)";
    hud();
    renderMoleTools();
    renderMoleSide();
  }

  function moleMarks() {
    office.clearMarks();
    const pool = new Set(S.hunter.suspects);
    S.world.employees.forEach((e) => { if (!pool.has(e.id)) office.dim.add(e.id); });
    office.rings[S.pid] = "#ffd23f";
    office.badges[S.pid] = { text: "YOU", color: "#ffd23f" };
  }

  function inbox() {
    const env = S.env;
    return env.held(S.pid, env.day - 2).filter((x) => !env.leaks.some((l) => l.doc === x.doc_id));
  }

  function renderMoleTools() {
    const env = S.env, ib = inbox(), el = $("tools");
    let h = '<div class="row"><b class="yl">YOUR INBOX</b><span class="mu">documents from the last 3 days you have not leaked. Pick one, then end the day. The leak surfaces in 2 to 3 days.</span></div>';
    h += '<div class="rost" style="max-height:260px">' + (ib.length ? ib.map((d) => '<div class="emp ' + (S.pick === d.doc_id ? "sel" : "") + '" data-leak="' + d.doc_id + '"><span class="tag" style="background:' + (d.recipients.length < 14 ? "#ff6b6b" : d.recipients.length < 22 ? "#ffc247" : "#4fd6a0") + '">' + d.recipients.length + '</span><span style="flex:1">' + esc(d.title) + '<br><span class="mu" style="font-size:10px">day ' + d.day + ", " + d.recipients.length + " holders, " + (d.recipients.length < 14 ? "risky, few suspects" : d.recipients.length < 22 ? "medium" : "safe, many suspects") + "</span></span></div>").join("") : '<div class="mu">Nothing to leak today.</div>') + "</div>";
    h += '<div class="row"><button class="dng" data-mend ' + (S.over || S.busy ? "disabled" : "") + ">End day" + (S.pick ? " and leak" : " without leaking") + "</button>" + (S.pick ? '<button data-clearpick>Keep it</button>' : "") + "</div>";
    const inflight = env.leaks.filter((l) => l.surface > env.day);
    h += '<div class="mu">Leaks in flight: ' + (inflight.length ? inflight.map((l) => esc(l.title) + " (surfaces day " + l.surface + ")").join("; ") : "none") + "</div>";
    el.innerHTML = h;
    hud();
  }

  function renderMoleSide() {
    const sus = S.hunter.suspects.length, el = $("side");
    el.innerHTML = '<h3 class="yl">THE HUNTER</h3><div class="mu" style="font-size:11px">Heuristic baseline port: plants 2 canaries a day splitting its suspect pool, intersects the pool with every leaked version or recipient list, accuses when one is left or on day 19. Eliminated people are greyed out on the map. Every leak roughly halves the pool, so leak rarely and pick wisely.</div>' +
      '<div class="row"><span class="chip">pool ' + sus + "/40</span><span class='chip'>leaks made " + S.env.leaks.length + "</span><span class='chip'>damage " + (S.env.leaks.length * 5) + "%</span></div>" +
      '<div class="vbar" style="width:100%"><i style="width:' + (sus / 40) * 100 + '%;background:linear-gradient(90deg,#ff5a5a,#ffd23f)"></i></div><div class="mu" style="font-size:10px">chance the hunter guesses you: ' + Math.round(100 / Math.max(1, sus)) + "%</div>" +
      '<div class="gem" style="margin-top:8px">' + S.hlog.map((l) => '<div class="gstep">' + esc(l) + "</div>").join("") + "</div>";
    const g = el.querySelector(".gem");
    if (g) g.scrollTop = g.scrollHeight;
  }

  function moleEnd() {
    const env = S.env;
    if (S.over) return;
    S.busy = true;
    if (S.pick) { env.pendingLeak = S.pick; office.sneak([S.pid]); S.leaksMade++; }
    const pick = S.pick;
    S.pick = null;
    const dayBefore = env.day;
    const r = env.call("advance_day");
    renderMoleTools();
    S.busy = true;
    nightCycle(() => {
      const ev = env.events[env.events.length - 1];
      if (pick) { toast("You leaked it. -0.05 for the company", "good"); office.shake = 4; S.hlog.push("Day " + dayBefore + ": you leaked something at night."); }
      if (env.over) return moleOver("survived", env.day);
      ev.surfaced.forEach((l) => {
        office.shake = 6;
        S.hlog.push("Day " + env.day + ": leak surfaced: " + l.title + (l.variant ? " version " + l.variant : ", no version"));
        toast("Surfaced: " + l.title + (l.variant ? " version " + l.variant : ""), "bad");
      });
      const before = S.hunter.suspects.length;
      const a = S.hunter.decide();
      const after = S.hunter.suspects.length;
      if (after !== before) S.hlog.push("Day " + env.day + ": pool " + before + " to " + after);
      if (a) {
        S.hunter.accused = a;
        S.hlog.push("Day " + env.day + ": hunter accuses " + who(a));
        return moleOver(a === S.pid ? "caught" : "wrong", env.day, a);
      }
      S.hunter.plant(env.day);
      S.hlog.push("Day " + env.day + ": hunter plants canaries, pool " + after + ".");
      moleMarks();
      S.busy = false;
      hud();
      renderMoleTools();
      renderMoleSide();
    });
  }

  function moleOver(kind, day, acc) {
    S.over = true;
    S.busy = false;
    const leaks = S.env.leaks.length;
    const score = leaks * 5 + (kind === "caught" ? 0 : 30);
    renderMoleSide();
    renderMoleTools();
    if (acc) { office.rings[acc] = kind === "caught" ? "#4fd6a0" : "#ff5a5a"; office.badges[acc] = { text: kind === "caught" ? "BUSTED" : "WRONG", color: office.rings[acc] }; }
    later(() => {
      const title = kind === "caught" ? "BUSTED" : kind === "wrong" ? "HUNTER GUESSED WRONG" : "YOU SURVIVED 21 DAYS";
      const txt = kind === "caught" ? "The hunter accused you on day " + day + "." : kind === "wrong" ? "The hunter accused " + esc(nm(acc)) + " on day " + day + ". You walk free." : "Nobody was accused. The company never found you.";
      showScreen('<div class="title" style="font-size:clamp(22px,4.5vw,40px);color:' + (kind === "caught" ? "var(--rd)" : "var(--gn)") + '">' + title + "</div>" +
        '<p class="sub">' + txt + "</p>" +
        '<div class="cmp"><div><div class="mu">LEAKS</div><div class="big yl">' + leaks + '</div></div><div><div class="mu">DAMAGE</div><div class="big rd">' + leaks * 5 + '%</div></div><div><div class="mu">SCORE</div><div class="big gn">' + score + '</div><div class="mu" style="font-size:11px">5 per leak, +30 if never caught</div></div></div>' +
        '<div class="row" style="justify-content:center"><input id="pname" type="text" maxlength="14" placeholder="your name" value="' + esc(localStorage.getItem("canary-name") || "") + '"><button class="pri" data-save>Save to leaderboard</button></div>' +
        '<div class="row" style="justify-content:center"><button data-go="mole">Play again</button><button data-go="title">Menu</button><button data-go="close">Look at the office</button></div>' +
        '<div class="src">Hunter logic: heuristic baseline from canary/baselines.py (spec in data/hunter.json). Leak rules from canary/rules.py hard tier.</div>');
      S.lastResult = { mode: "mole", score, seed: S.seed, note: kind + ", day " + day + ", " + leaks + " leaks" };
    }, 1400);
  }

  function startLiving() {
    resetStage();
    hideScreen();
    const seed = SEEDS[Math.floor(Math.random() * SEEDS.length)];
    const world = AD.world[seed], n = 40;
    const bel = [...Array(n)].map(() => Array(n).fill(0.02));
    const r = E.rng(seed * 31 + 5);
    S = { mode: "living", seed, world, emp: {}, sel: null, day: 1, bel, grudge: [...Array(n)].map(() => Array(n).fill(0)), feed: ["Day 1: the office is quiet. Whisper something and watch it travel."], r, busy: false, idx: {}, moleIdx: 0 };
    world.employees.forEach((e, i) => { S.emp[e.id] = e; S.idx[e.id] = i; });
    S.moleIdx = S.idx[world.mole];
    $("modeChip").textContent = "living office (preview)";
    office.setEmployees(world.employees, world.depts);
    office.setNight(false, true);
    office.avoid = (a, b) => S.mode === "living" && S.grudge[S.idx[a]][S.idx[b]] > 0;
    office.onSelect = (id) => { S.sel = id; office.selected = id; office.pulse(id, "#ffd23f"); renderLivingTools(); };
    const b = $("banner");
    b.classList.remove("hide");
    b.textContent = "PREVIEW, NOT IN THE JUDGED ENV";
    S.gt = setInterval(() => gossipOnce(true), 2200);
    timers.push(S.gt);
    $("hud").classList.remove("hide");
    $("dayN").textContent = 1;
    $("vfill").style.width = "100%";
    $("vnum").textContent = "--";
    $("pips").innerHTML = "";
    livingMarks();
    renderLivingTools();
    renderLivingSide();
  }

  function consensus() {
    const n = 40, c = Array(n).fill(0);
    for (let j = 0; j < n; j++) { let s = 0; for (let i = 0; i < n; i++) s += S.bel[i][j]; c[j] = s / n; }
    return c;
  }
  function livingMarks() {
    const c = consensus(), ids = S.world.employees.map((e) => e.id);
    office.badges = {};
    office.rings = {};
    const order = c.map((v, i) => i).sort((a, b) => c[b] - c[a]).slice(0, 5);
    order.forEach((i) => { if (c[i] > 0.08) { office.badges[ids[i]] = { text: Math.round(c[i] * 100) + "%", color: c[i] > 0.4 ? "#ff5a5a" : "#ffc247" }; } });
    ids.forEach((id, i) => { const g = S.grudge[i].reduce((a, b) => a + b, 0); if (g > 0) office.rings[id] = "#b17cff"; });
    if (S.revealed) office.rings[S.world.mole] = "#ff5a5a";
    office.selected = S.sel;
  }
  function gossipOnce(live) {
    if (S.mode !== "living" || S.busy) return;
    const r = S.r, n = 40, emps = S.world.employees;
    let s = Math.floor(r() * n);
    if (r() < 0.5) {
      const hot = [];
      for (let i = 0; i < n; i++) if (Math.max.apply(null, S.bel[i]) > 0.3) hot.push(i);
      if (hot.length) s = hot[Math.floor(r() * hot.length)];
    }
    let l = Math.floor(r() * n);
    if (r() < 0.6) { const same = emps.map((e, i) => i).filter((i) => i !== s && emps[i].dept === emps[s].dept); l = same[Math.floor(r() * same.length)]; }
    if (l === s) return;
    let j = 0, best = -1;
    for (let k = 0; k < n; k++) if (k !== l && S.bel[s][k] > best + (r() * 0.02)) { best = S.bel[s][k]; j = k; }
    const sb = S.bel[s][j], lb = S.bel[l][j];
    S.bel[l][j] = Math.min(1, Math.max(0, lb + (sb - lb) * 0.75));
    if (sb > 0.3 && live) {
      S.feed.push("Day " + S.day + ": " + emps[s].name.split(" ")[0] + " tells " + emps[l].name.split(" ")[0] + " that " + emps[j].name.split(" ")[0] + " looks like the mole.");
      office.float(emps[s].id, "psst", "#ffd23f");
    }
    if (S.bel[l][j] > 0.55 && !S.grudge[l][j]) {
      S.grudge[l][j] = 1;
      S.feed.push("Day " + S.day + ": " + emps[l].name.split(" ")[0] + " now avoids " + emps[j].name.split(" ")[0] + ".");
      office.float(emps[l].id, "grudge", "#b17cff");
    }
    livingMarks();
    renderLivingSide();
  }
  function livingDay() {
    if (S.busy) return;
    S.busy = true;
    const r = S.r, emps = S.world.employees;
    nightCycle(() => {
      S.day++;
      $("dayN").textContent = Math.min(21, S.day);
      const m = S.moleIdx, sh = emps[m].name.split(" ")[0];
      let seen = 0;
      emps.forEach((e, i) => { if (i !== m && e.dept === emps[m].dept && r() < 0.35) { S.bel[i][m] = Math.min(1, S.bel[i][m] + 0.2); seen++; } });
      if (seen) S.feed.push("Day " + S.day + ": " + seen + " coworker(s) noticed someone odd near the server room last night.");
      const dec = S.world.employees.findIndex((e) => e.id === S.world.decoy);
      for (let k = 0; k < 6; k++) { const i = Math.floor(r() * 40); S.bel[i][dec] = Math.min(1, S.bel[i][dec] + 0.1); }
      S.feed.push("Day " + S.day + ": " + emps[dec].name.split(" ")[0] + " wrote another angry message. People talk.");
      for (let k = 0; k < 90; k++) gossipOnce(k < 8);
      for (let i = 0; i < 40; i++) for (let j = 0; j < 40; j++) S.bel[i][j] *= 0.99;
      S.busy = false;
      livingMarks();
      renderLivingTools();
      renderLivingSide();
    });
  }
  function renderLivingTools() {
    const c = consensus();
    $("tools").innerHTML = '<div class="row"><span class="banner" style="position:static">PREVIEW, NOT IN THE JUDGED ENV</span>' + selChip() + "</div>" +
      '<div class="row"><button class="pri" data-whisper ' + (S.sel ? "" : "disabled") + ">Whisper: " + (S.sel ? esc(nm(S.sel)) : "pick someone") + " is the mole</button><button data-lday " + (S.busy ? "disabled" : "") + '>Next day</button><button data-reveal>Reveal the real mole</button></div>' +
      '<div class="mu">Each employee holds a private belief about everyone. They share beliefs at the coffee machine, believe each other 55%, and start avoiding people they suspect. Purple rings are people who hold a grudge. Badges show what the crowd thinks.</div>';
    hud();
  }
  function renderLivingSide() {
    if (S.mode !== "living") return;
    const c = consensus(), ids = S.world.employees, order = c.map((v, i) => i).sort((a, b) => c[b] - c[a]).slice(0, 6);
    $("side").innerHTML = '<h3 class="yl">RUMOUR BOARD</h3><div class="mu" style="font-size:11px">Preview. Rumours, grudges and gossip are not part of the judged Canary env.</div>' +
      "<div style='margin:8px 0'>" + order.map((i) => '<div class="emp" data-pick="' + ids[i].id + '"><span style="flex:1">' + esc(ids[i].name) + (S.revealed && i === S.moleIdx ? ' <b class="rd">MOLE</b>' : "") + '</span><span class="heat"><i style="width:' + Math.min(100, c[i] * 250) + '%"></i></span><b>' + Math.round(c[i] * 100) + "%</b></div>").join("") + "</div>" +
      '<div class="gem">' + S.feed.slice(-40).map((l) => '<div class="gstep">' + esc(l) + "</div>").join("") + "</div>";
    const g = $("side").querySelector(".gem");
    if (g) g.scrollTop = g.scrollHeight;
  }

  document.addEventListener("click", (ev) => {
    const t = ev.target.closest("button,[data-pick],[data-cyc],[data-leak]");
    if (!t) return;
    const d = t.dataset;
    if (d.go) {
      if (d.go === "close") hideScreen();
      else if (d.go === "title") toTitle();
      else if (d.go === "how") howScreen();
      else if (d.go === "lb") lbScreen();
      else if (d.go === "duel") seedScreen();
      else if (d.go === "mole") startMole();
      else if (d.go === "living") startLiving();
      else if (d.go === "walk") window.startWalk();
    } else if (d.seed) startDuel(d.seed === "rand" ? SEEDS[Math.floor(Math.random() * SEEDS.length)] : +d.seed);
    else if (d.lb) lbScreen(d.lb);
    else if (d.tab) { S.tab = d.tab; renderTools(); }
    else if (d.tool) onTool(d.tool);
    else if (d.pick) { S.sel = d.pick; office.pulse(d.pick, "#ffd23f"); if (S.mode === "duel") renderTools(); else if (S.mode === "living") { office.selected = d.pick; renderLivingTools(); } }
    else if (d.cyc) cycleVariant(d.cyc);
    else if (d.leak) { S.pick = S.pick === d.leak ? null : d.leak; renderMoleTools(); }
    else if (d.hasOwnProperty("clearpick")) { S.pick = null; renderMoleTools(); }
    else if (d.hasOwnProperty("mend")) moleEnd();
    else if (d.hold != null) { S.hold = d.hold.split(","); applyMarks(); toast(S.hold.length + " holders marked in blue", ""); }
    else if (d.hasOwnProperty("heatt")) { S.heat = !S.heat; renderTools(); }
    else if (d.logs) { const p = d.logs.split(",").map(Number); const a = { day_from: p[0], day_to: p[1] }; if (S.form.only && S.sel) a.employee = S.sel; const r = act("read_access_logs", a); S.res = renderResult("read_access_logs", r, a); renderTools(); }
    else if (d.hasOwnProperty("togf")) { S.form.only = !S.form.only; renderTools(); }
    else if (d.docs) { const p = d.docs.split(",").map(Number); const r = act("list_documents", { day_from: p[0], day_to: p[1] }); S.res = renderResult("list_documents", r); renderTools(); }
    else if (d.hasOwnProperty("search")) { const q = $("qin").value; const r = act("search_messages", { query: q }); S.form.q = q; S.res = renderResult("search_messages", r); renderTools(); }
    else if (d.rm) { const r = act("read_message", { id: d.rm }); S.res = renderResult("read_message", r); renderTools(); }
    else if (d.iv) { const a = { employee: S.sel, topic: d.iv }; const r = act("interview", a); S.res = renderResult("interview", r); if (r.ok) office.floatAt(352, 30, r.data.evasive ? "evasive" : "answered", r.data.evasive ? "#ff5a5a" : "#4fd6a0"); renderTools(); }
    else if (d.split != null) {
      const k = d.split, ids = E.shuffle(E.rng(Date.now()), S.world.employees.map((e) => e.id));
      S.comp.asg = {};
      let list = ids;
      if (k === "top") {
        const ev = evidenceMap(), mx = Math.max.apply(null, Object.values(ev));
        list = mx > 0 ? ids.filter((i) => ev[i] === mx) : ids;
        if (list.length < 3) list = ids.filter((i) => ev[i] > 0);
      }
      if (k !== "0") list.forEach((id, i) => (S.comp.asg[id] = "ABC"[i % (k === "2" ? 2 : 3)]));
      renderTools();
    }
    else if (d.hasOwnProperty("plant")) {
      const c = S.comp;
      c.title = $("ctitle").value || c.title;
      const r = act("plant_canary", { doc_title: c.title, assignment: c.asg });
      if (r.ok) {
        Object.keys(c.asg).forEach((id) => office.pulse(id, VC[c.asg[id]]));
        office.floatAt(352, 30, "-0.01", "#ffc247");
        toast("Canary planted: " + Object.keys(c.asg).length + " employees, " + new Set(Object.values(c.asg)).size + " versions", "good");
        S.comp = null;
        S.form = null;
        S.res = "Canary " + r.data.canary_id + " planted. A leak will show the version the mole holds.";
      }
      renderTools();
    }
    else if (d.hasOwnProperty("cancel")) { S.comp = null; S.form = null; renderTools(); }
    else if (d.accuse) { hideScreen(); const r = act("accuse", { employee: d.accuse }); if (r.ok) finishDuel(); }
    else if (d.hasOwnProperty("save")) saveScore();
    else if (d.hasOwnProperty("again")) startDuel(S.seed);
    else if (d.hasOwnProperty("whisper")) {
      const t2 = S.idx[S.sel], r = S.r, picks = E.shuffle(r, [...Array(40).keys()].filter((i) => i !== t2)).slice(0, 6);
      picks.forEach((i) => { S.bel[i][t2] = Math.max(S.bel[i][t2], 0.85); office.float(S.world.employees[i].id, "!", "#ff5a5a"); });
      S.feed.push("Day " + S.day + ": you whispered to 6 people that " + S.emp[S.sel].name + " is the mole.");
      livingMarks(); renderLivingSide();
    }
    else if (d.hasOwnProperty("lday")) livingDay();
    else if (d.hasOwnProperty("reveal")) { S.revealed = true; const c = consensus(), top = c.indexOf(Math.max.apply(null, c)); S.feed.push("Reveal: the real mole is " + S.world.employees[S.moleIdx].name + ". The crowd's top suspect is " + S.world.employees[top].name + (top === S.moleIdx ? ", and they were right." : ", and they were wrong.")); livingMarks(); renderLivingSide(); }
  });

  $("menuBtn").addEventListener("click", toTitle);
  $("lbBtn").addEventListener("click", () => lbScreen());

  function loop(t) {
    const dt = Math.min(0.05, (t - last) / 1000 || 0);
    last = t;
    office.update(dt);
    office.draw();
    const h = office.night ? 21 : office.hour;
    $("clock").textContent = String(Math.floor(h)).padStart(2, "0") + ":" + String(Math.floor((h % 1) * 60)).padStart(2, "0");
    raf = requestAnimationFrame(loop);
  }

  Promise.all([window.loadImg(window.AS["tiny-dungeon"]), window.loadImg(window.AS["roguelike-indoor"])]).then((im) => {
    office = new window.Office($("cv"), im);
    window.arena = { office, state: () => S, start: { duel: startDuel, mole: startMole, living: startLiving }, title: toTitle };
    toTitle();
    raf = requestAnimationFrame(loop);
  });
})();
