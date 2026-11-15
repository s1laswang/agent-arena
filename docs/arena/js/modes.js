(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const DC = ["#5bd1ff", "#ff8ad8", "#b6f06a", "#ffd23f", "#b17cff", "#ff9a3c"];
  const SEEDS = [26, 0, 2, 6];
  let timer = 0, G = null, keyFn = null;

  function show(html) {
    const s = $("screen");
    s.innerHTML = '<div class="card">' + html + "</div>";
    s.classList.remove("hide", "ttl");
    s.scrollTop = 0;
  }
  function stop() { clearInterval(timer); timer = 0; keyFn = null; }
  function menu() { stop(); window.arena.title(); }
  function ini(n) { return n.split(" ").map((w) => w[0]).join(""); }
  function dcol(d) { return DC[["Engineering", "Finance", "Sales", "Legal", "Research"].indexOf(d) % 6 + 0] || DC[5]; }
  function nm(sd, id) { const e = window.SD[sd].emp[id]; return e ? e[0] : id; }

  const SOLVER_CSS = "<style>.xs{display:grid;grid-template-columns:1fr 1fr;gap:8px}.xp{background:var(--pn2);border:3px solid var(--ln);border-radius:6px;padding:10px;text-align:center;min-width:0}.xp h3{color:var(--yl);font-size:15px}.xp .d{font-size:30px;font-weight:900;margin:4px 0}.xp .vbar{width:100%;height:16px;margin:6px 0}.xt{display:flex;flex-wrap:wrap;gap:3px;justify-content:center;min-height:20px;margin:6px 0}.xt i{width:14px;height:14px;background:var(--yl);border:2px solid #a8861a;border-radius:3px 7px 3px 3px;display:block}.xr{font-size:20px;font-weight:900;min-height:56px;display:flex;align-items:center;justify-content:center;flex-direction:column}.xc{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin:10px 0}.xc button{min-height:56px;min-width:56px;font-size:16px;padding:8px 16px}.xa{font-size:12px;color:var(--mu);min-height:18px}.cite{color:var(--mu);font-size:11px;text-align:center;margin-top:10px}@media(max-width:600px){.xp{padding:6px}.xp h3{font-size:12px}.xp .d{font-size:22px}}</style>";

  function seedPick() {
    show(SOLVER_CSS + '<h2 class="yl" style="text-align:center">OUR SOLVER vs GEMINI</h2><p class="sub">Same office. Same seed. Pick one.</p><div class="xc">' +
      SEEDS.map((s) => '<button class="big" data-xs="' + s + '">SEED ' + s + "</button>").join("") + '</div><div class="xc"><button class="big" data-go="title">BACK</button></div>' +
      '<div class="cite">Committed v1.4 hard runs, data/runs/committed/v1.4</div>');
    keyFn = (k) => { const i = "1234".indexOf(k); if (i >= 0) startSolver(SEEDS[i]); else if (k === "Escape") menu(); };
  }

  function panel(label, side, sd, day) {
    const n = side.days.length, d = Math.min(day, n), done = day >= n;
    let v = 1, traps = 0;
    for (let i = 0; i < d; i++) { traps += side.days[i][0]; v = side.days[i][4]; }
    if (!done && d > 0) v = side.days[d - 1][4];
    let last = "";
    if (d > 0 && !done) { const x = side.days[d - 1]; last = (x[0] ? "TRAP x" + x[0] + " " : "") + (x[1] ? "FEED x" + x[1] + " " : "") + (x[2] ? "ASK x" + x[2] + " " : "") + (x[3] ? "READ x" + x[3] : ""); }
    const res = done ? '<div class="' + (side.ok ? "gn" : "rd") + '">' + (side.ok ? "RIGHT" : "WRONG") + '</div><div style="font-size:13px">' + esc(nm(sd, side.acc)) + "</div>" : '<div class="mu">investigating</div>';
    return '<div class="xp"><h3>' + label + '</h3><div class="d">DAY ' + Math.max(d, 1) + '</div><div class="vbar"><i style="width:' + Math.round(v * 100) + '%"></i></div><b class="yl">' + v.toFixed(2) + '</b><div class="xt">' + "<i></i>".repeat(Math.min(traps, 40)) + '</div><div class="xa">' + traps + " traps</div><div class=\"xa\">" + last + "</div><div class=\"xr\">" + res + "</div>" + (done ? '<div class="big ' + (side.score < 0 ? "rd" : "gn") + '" style="font-size:28px;font-weight:900">' + side.score.toFixed(2) + "</div>" : "") + "</div>";
  }

  function startSolver(sd) {
    stop();
    G = { sd, day: 0, play: true, sp: 1 };
    renderSolver();
    timer = setInterval(tick, 150);
    keyFn = (k) => {
      if (k === " " || k === "Enter") { G.play = !G.play; renderSolver(); }
      else if (k === "s") { G.sp = G.sp === 1 ? 2 : G.sp === 2 ? 4 : 1; renderSolver(); }
      else if (k === "Escape") seedPick();
    };
  }
  let acc = 0;
  function tick() {
    if (!G || !G.play) return;
    acc += 150 * G.sp;
    if (acc < 900) return;
    acc = 0;
    const D = window.SD[G.sd], mx = Math.max(D.solver.days.length, D.gemini.days.length);
    if (G.day <= mx) G.day++;
    if (G.day > mx) { G.play = false; endSolver(); return; }
    renderSolver();
  }
  function renderSolver() {
    const D = window.SD[G.sd];
    show(SOLVER_CSS + '<div class="xs">' + panel("OUR SOLVER", D.solver, G.sd, G.day) + panel("GEMINI-4-CARBON", D.gemini, G.sd, G.day) + '</div><div class="xc"><button class="pri big" data-xplay>' + (G.play ? "PAUSE" : "PLAY") + '</button><button class="big" data-xspeed>' + G.sp + 'x</button><button class="big" data-xs="' + G.sd + '">RESTART</button><button class="big" data-xseeds>SEEDS</button></div><div class="cite">Seed ' + G.sd + ". Committed v1.4 hard runs.</div>");
  }
  function endSolver() {
    const D = window.SD[G.sd], a = D.solver, b = D.gemini, w = a.score > b.score ? "OUR SOLVER WINS" : a.score < b.score ? "GEMINI WINS" : "TIE";
    const c = (x, l, win) => '<div class="' + (win ? "win" : "") + '"><div class="mu">' + l + '</div><div class="big ' + (x.score < 0 ? "rd" : "gn") + '">' + x.score.toFixed(2) + "</div><div>" + (x.ok ? '<b class="gn">RIGHT</b>' : '<b class="rd">WRONG</b>') + " " + esc(nm(G.sd, x.acc)) + '</div><div class="mu" style="font-size:12px">accused day ' + x.fd + "</div></div>";
    show(SOLVER_CSS + '<div class="title" style="font-size:clamp(22px,5vw,40px)">' + w + '</div><p class="sub">Seed ' + G.sd + "</p><div class=\"cmp\">" + c(a, "OUR SOLVER", a.score >= b.score) + c(b, "GEMINI-4-CARBON", b.score >= a.score) + '</div><p class="how" style="font-size:15px;text-align:center">Hard, MCP tools only, n=30: Gemini scores <b class="yl">65%</b> of the solver (<b class="yl">72%</b> luck-adjusted). In the full judge path (Harbor, where it also has a shell) it matched the solver: 93-153% over 3 runs.</p><div style="margin:12px auto;max-width:600px;padding:10px 12px;border:3px solid var(--ln);border-radius:6px;background:var(--pn2);font-size:14px"><div style="text-align:center;font-weight:800;color:var(--yl);margin-bottom:6px">OUR SMALL MODEL vs GEMINI &middot; hard tier, average score</div><div style="display:flex;justify-content:space-between;gap:10px"><span>Gemini-4-carbon (MCP tools only, n=30)</span><b>+0.322</b></div><div style="display:flex;justify-content:space-between;gap:10px"><span>Our model: Qwen2.5-1.5B, RL-trained on Canary (609 steps, n=60)</span><b>-0.033</b></div><div style="display:flex;justify-content:space-between;gap:10px;color:var(--mu)"><span>Same model, untrained (n=11)</span><b>0.000</b></div><div style="font-size:12px;margin-top:6px;color:var(--mu)">Training took it from 3% to 100% valid moves. It now mostly holds back (no accusation in 97% of hard games): it has not learned to gather evidence yet. Its test games are different held-out worlds from Gemini&#39;s, so this is not a same-case match. Source: fr8/analysis/out/ws4_table_final.md (branch justSilas-fr8).</div></div><div class="xc"><button class="pri big" data-xseeds>OTHER SEED</button><button class="big" data-xs="' + G.sd + '">REPLAY</button><button class="big" data-go="title">MENU</button></div><div class="cite">docs/reports/gap.md, v1.4: hard 65% [24%, 98%], luck-adj 72% [52%, 91%]; medium 111%. Harbor: results/harbor/rehearsal/TABLE.md. Seed scores from episodes.jsonl in data/runs/committed/v1.4.</div>');
    keyFn = (k) => { if (k === "Escape") seedPick(); else if (k === "Enter") startSolver(G.sd); };
  }

  const EASY_CSS = "<style>.ep{display:flex;flex-direction:column;gap:10px}.eh{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;font-size:18px;font-weight:800}.eh .vbar{width:140px;height:16px}.ec{display:flex;flex-direction:column;gap:10px}.ec button{min-height:64px;font-size:20px;font-weight:800;text-align:left;padding:10px 18px;display:flex;justify-content:space-between;align-items:center}.ec button kbd{opacity:.6;font-size:14px}.pg{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.pg button{min-height:88px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;font-size:15px;padding:6px}.pg canvas{width:48px;height:48px;image-rendering:pixelated;background:#0d121c;border-radius:4px}.em{background:#0d121c;border:2px solid var(--ln);border-radius:6px;padding:10px;font-size:17px;min-height:56px}.eb{min-height:56px;font-size:18px;font-weight:800}@media(max-width:600px){.eh{font-size:15px}}</style>";

  function portrait(e) {
    const o = window.arena.office.byId[e.id], c = document.createElement("canvas");
    c.width = 16; c.height = 16;
    if (o && o.spr) c.getContext("2d").drawImage(o.spr, 0, 0);
    return c;
  }
  function portraits(list, attr) {
    const wrap = document.createElement("div");
    wrap.className = "pg";
    list.forEach((e, i) => {
      const b = document.createElement("button");
      b.className = "big";
      b.dataset[attr] = e.id;
      b.appendChild(portrait(e));
      const t = document.createElement("span");
      t.innerHTML = "<b>" + (i + 1) + "</b> " + esc(e.name) + '<br><span class="mu" style="font-size:12px">' + esc(e.dept) + "</span>";
      b.appendChild(t);
      wrap.appendChild(b);
    });
    return wrap;
  }
  function mount(html, extra) {
    show(EASY_CSS + '<div class="ep">' + html + '<div id="ex"></div></div>');
    if (extra) $("ex").appendChild(extra);
  }
  function head() {
    const e = G.env;
    return '<div class="eh"><span>DAY <b class="yl">' + e.day + '</b>/21</span><span class="vbar"><i style="width:' + Math.round(Math.max(0, e.Vtrue) * 100) + '%"></i></span><span class="yl">' + Math.max(0, e.Vtrue).toFixed(2) + '</span><button data-go="title" style="min-height:44px">MENU</button></div>';
  }
  function topSuspects() {
    const ev = G.env.evidence(), r = window.Eng.rng(Date.now());
    const l = window.Eng.shuffle(r, G.world.employees.slice());
    l.sort((a, b) => ev[b.id] - ev[a.id]);
    return { list: l.slice(0, 4), max: ev[l[0].id], n: l.filter((x) => ev[x.id] === ev[l[0].id]).length };
  }

  function startEasy(seed) {
    stop();
    const seeds = window.AD.index.seeds.map((s) => s.seed);
    if (seed == null) seed = seeds[Math.floor(Math.random() * seeds.length)];
    const world = window.AD.world[seed];
    window.arena.office.setEmployees(world.employees, world.depts);
    G = { seed, world, env: new window.Eng.Env(world, seed), note: "" };
    easyDay();
  }
  function easyDay() {
    const html = head() + (G.note ? '<div class="em">' + G.note + "</div>" : "") +
      '<div class="ec"><button class="pri" data-e="trap">PLANT A TRAP <kbd>1</kbd></button><button data-e="feed">READ THE LEAK FEED <kbd>2</kbd></button><button data-e="ask">INTERVIEW SOMEONE <kbd>3</kbd></button><button class="dng" data-e="acc">ACCUSE <kbd>4</kbd></button></div>';
    mount(html);
    keyFn = (k) => { const m = { 1: "trap", 2: "feed", 3: "ask", 4: "acc", a: "acc" }[k]; if (m) easyDo(m); };
  }
  function easyDo(k) {
    const e = G.env;
    if (k === "trap") {
      const r = window.Eng.rng(Date.now()), ids = window.Eng.shuffle(r, G.world.employees.map((x) => x.id)), asg = {};
      ids.forEach((id, i) => (asg[id] = "ABC"[i % 3]));
      const t = window.AD.vocab.title_templates[Math.floor(r() * window.AD.vocab.title_templates.length)].replace("{q}", "Q" + (1 + Math.floor(r() * 4))).replace("{d}", window.AD.vocab.depts[0]).replace("{p}", window.AD.vocab.projects[0]);
      e.call("plant_canary", { doc_title: t, assignment: asg });
      endDay("Trap planted. 3 copies handed out.");
    } else if (k === "feed") {
      e.call("check_leak_feed", {});
      const s = topSuspects(), n = e.feed().length;
      endDay(n ? n + " leak" + (n > 1 ? "s" : "") + " seen. " + (s.max ? s.n + " suspect" + (s.n > 1 ? "s" : "") + " left." : "No trap copy leaked yet.") : "Nothing leaked yet.");
    } else if (k === "ask") {
      const r = window.Eng.rng(Date.now());
      const l = window.Eng.shuffle(r, G.world.employees.slice()).slice(0, 4);
      mount(head() + '<div class="em">Who do you ask?</div>', portraits(l, "ep"));
      keyFn = (c) => { const i = "1234".indexOf(c); if (i >= 0) easyAsk(l[i].id); else if (c === "Escape") easyDay(); };
    } else if (k === "acc") {
      const s = topSuspects();
      mount(head() + '<div class="em">Who is the mole?</div>', portraits(s.list, "ea"));
      $("ex").insertAdjacentHTML("beforeend", '<div style="margin-top:10px"><button class="big" data-e="back">NOT YET</button></div>');
      keyFn = (c) => { const i = "1234".indexOf(c); if (i >= 0) easyAccuse(s.list[i].id); else if (c === "Escape") easyDay(); };
    } else if (k === "back") easyDay();
  }
  function easyAsk(id) {
    const r = G.env.call("interview", { employee: id, topic: "recent_documents" });
    const a = r.ok ? '"' + esc(r.data.answer) + '"' : "No time.";
    endDay(esc(G.world.employees.find((x) => x.id === id).name) + ": " + a);
  }
  function endDay(msg) {
    const e = G.env, d = e.day;
    mount(head() + '<div class="em">' + msg + '</div><div class="ec"><button class="pri" data-e="next">NEXT DAY <kbd>Enter</kbd></button><button class="dng" data-e="acc">ACCUSE <kbd>4</kbd></button></div>');
    keyFn = (k) => { if (k === "Enter" || k === " " || k === "1") nextDay(); else if (k === "4" || k === "a") easyDo("acc"); };
    G.pending = d;
  }
  function nextDay() {
    const r = G.env.call("advance_day", {});
    if (G.env.over) return easyEnd();
    G.note = "";
    easyDay();
  }
  function easyAccuse(id) {
    G.env.call("accuse", { employee: id });
    easyEnd();
  }
  function easyEnd() {
    const e = G.env, w = G.world, mole = w.employees.find((x) => x.id === w.mole), row = window.AD.index.seeds.find((x) => x.seed === G.seed);
    const right = e.accused && e.correct, sc = e.score;
    const c = (l, s, ok, who) => '<div><div class="mu">' + l + '</div><div class="big ' + (s < 0 ? "rd" : "gn") + '">' + s.toFixed(2) + '</div><div class="mu" style="font-size:12px">' + who + "</div></div>";
    show(EASY_CSS + '<div class="title" style="font-size:clamp(22px,5vw,40px)">' + (e.accused ? (right ? "CAUGHT HIM" : "WRONG PERSON") : "NO ACCUSATION") + '</div><p class="sub">The mole was <b class="rd">' + esc(mole.name) + "</b>, " + esc(mole.dept) + '.</p><div class="cmp">' +
      c("YOU", sc, right, "day " + Math.min(e.day, 21)) + c("GEMINI", row.gemini.score, row.gemini.correct, row.gemini.correct ? "right" : "wrong") + c("SOLVER", row.solver.score, row.solver.correct, row.solver.correct ? "right" : "wrong") +
      '</div><div class="ec"><button class="pri" data-e="again">PLAY AGAIN <kbd>Enter</kbd></button><button data-go="title">MENU</button></div>');
    keyFn = (k) => { if (k === "Enter") startEasy(); else if (k === "Escape") menu(); };
  }

  document.addEventListener("click", (ev) => {
    const t = ev.target.closest("button");
    if (!t) return;
    const d = t.dataset;
    if (d.go === "solver") seedPick();
    else if (d.go === "easy") startEasy();
    else if (d.go === "title") stop();
    else if (d.xs != null) startSolver(+d.xs);
    else if (d.xplay != null) { G.play = !G.play; renderSolver(); }
    else if (d.xspeed != null) { G.sp = G.sp === 1 ? 2 : G.sp === 2 ? 4 : 1; renderSolver(); }
    else if (d.xseeds != null) { stop(); seedPick(); }
    else if (d.e) { if (d.e === "next") nextDay(); else if (d.e === "again") startEasy(); else easyDo(d.e); }
    else if (d.ep) easyAsk(d.ep);
    else if (d.ea) easyAccuse(d.ea);
  });
  document.addEventListener("keydown", (ev) => {
    if (!keyFn || ev.target.tagName === "INPUT" || ev.metaKey || ev.ctrlKey) return;
    keyFn(ev.key.length === 1 ? ev.key.toLowerCase() : ev.key);
    if ([" ", "Enter"].includes(ev.key)) ev.preventDefault();
  });
})();
