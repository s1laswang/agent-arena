(function () {
  const TW = 16, GW = 44, GH = 26, SPD = 5.625, HB = 0.28;
  const DEPTS = ["Engineering", "Finance", "Sales", "Legal", "Research"];
  const DCOL = ["#4aa3ff", "#ffc247", "#ff6b6b", "#b17cff", "#4fd6a0"];
  const POD = { Engineering: [12, 3], Finance: [26, 3], Sales: [26, 11], Legal: [12, 11], Research: [12, 19] };
  const ROOM = {
    player_start: [24, 13], desk_pc: [27, 21], server_term: [5, 4], feed_tv: [22, 2], printer: [40, 21],
    bell: [40, 13], red_door: [43, 5], case_board: [1, 13], coffee: [40, 8]
  };
  const COFFEE = [[39, 9], [40, 9], [41, 9], [42, 9], [39, 10], [41, 10]];
  const BASES = [[0, 7], [1, 7], [2, 7], [3, 7], [4, 7], [0, 8], [1, 8], [2, 8], [3, 8], [4, 8], [4, 9]];
  const VC = { A: "#5bd1ff", B: "#ff8ad8", C: "#b6f06a" };
  const ICONS = {
    monitor: '<rect x="3" y="4" width="18" height="12"/><path d="M9 20h6M12 16v4"/>',
    rack: '<rect x="5" y="3" width="14" height="5"/><rect x="5" y="10" width="14" height="5"/><rect x="5" y="17" width="14" height="4"/><path d="M8 5.5h.01M8 12.5h.01"/>',
    tv: '<rect x="3" y="7" width="18" height="12"/><path d="M8 3l4 4 4-4"/>',
    printer: '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8"/><rect x="7" y="14" width="10" height="7"/>',
    bell: '<path d="M6 17v-6a6 6 0 0 1 12 0v6l2 2H4z"/><path d="M10 22h4"/>',
    door: '<rect x="6" y="3" width="12" height="18"/><path d="M15 12h.01"/>',
    pin: '<path d="M12 21v-7M7 14h10l-2-6V3H9v5z"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    desk: '<path d="M3 9h18M5 9v10M19 9v10M3 5h18v4"/>',
    mat: '<rect x="3" y="8" width="18" height="8"/><path d="M7 12h10"/>',
    docs: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    people: '<circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c0-4 3-6 6-6s6 2 6 6M15 14c3 0 6 1 6 5"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    key: '<circle cx="8" cy="12" r="4"/><path d="M12 12h9M18 12v4M21 12v3"/>',
    mail: '<rect x="3" y="5" width="18" height="14"/><path d="M3 6l9 7 9-7"/>',
    log: '<path d="M5 4h14v16H5z"/><path d="M9 9h6M9 13h6M9 17h3"/>',
    paper: '<path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    shrug: '<circle cx="12" cy="12" r="9"/><path d="M8 15.5h8M8.5 9.5h.01M15.5 9.5h.01"/>',
    repeat: '<path d="M17 3l4 4-4 4M21 7H8a4 4 0 0 0-4 4M7 21l-4-4 4-4M3 17h13a4 4 0 0 0 4-4"/>',
    moon: '<path d="M20 14A8 8 0 0 1 10 4a8 8 0 1 0 10 10z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
    x: '<path d="M5 5l14 14M19 5L5 19"/>',
    check: '<path d="M4 12l5 5L20 6"/>',
    search: '<circle cx="10" cy="10" r="6"/><path d="M15 15l6 6"/>',
    send: '<path d="M3 11L21 3l-8 18-2-8z"/>',
    back: '<path d="M9 5L3 12l6 7M3 12h18"/>',
    calendar: '<rect x="3" y="5" width="18" height="16"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    coin: '<circle cx="12" cy="12" r="9"/><path d="M12 7v10M9 10c0-2 6-2 6 0s-6 1-6 4 6 3 6 0"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-5 4-7 8-7s8 2 8 7"/>',
    coffee: '<path d="M5 8h12v8a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4zM17 10h2a2 2 0 0 1 0 5h-2"/>'
  };
  function icon(k, s) {
    s = s || 24;
    return '<svg class="w-ic" width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[k] || ICONS.pin) + "</svg>";
  }
  function shapeSvg(l, s) {
    s = s || 20;
    const c = VC[l] || "#fff", b = '<svg class="w-ic" width="' + s + '" height="' + s + '" viewBox="0 0 20 20" fill="' + c + '" stroke="#10151f" stroke-width="2">';
    return b + (l === "A" ? '<rect x="3" y="3" width="14" height="14"/>' : l === "B" ? '<circle cx="10" cy="10" r="7.5"/>' : '<path d="M10 2.5L18 17H2z"/>') + "</svg>";
  }
  function shapeDraw(g, l, x, y, s) {
    g.fillStyle = VC[l] || "#fff";
    g.strokeStyle = "#10151f";
    g.lineWidth = 1;
    g.beginPath();
    if (l === "A") g.rect(x, y, s, s);
    else if (l === "B") g.arc(x + s / 2, y + s / 2, s / 2, 0, 6.2832);
    else { g.moveTo(x + s / 2, y); g.lineTo(x + s, y + s); g.lineTo(x, y + s); g.closePath(); }
    g.fill();
    g.stroke();
  }
  function hsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
    let h = 0, s = 0;
    if (mx !== mn) {
      const d = mx - mn;
      s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
      h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
      h *= 60;
    }
    return [h, s, l];
  }
  function rgb(h, s, l) {
    h = (((h % 360) + 360) % 360) / 360;
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
    const f = (t) => {
      t = (t + 1) % 1;
      return t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p;
    };
    return [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
  }
  function sprite(td, base, grp) {
    const cv = document.createElement("canvas");
    cv.width = cv.height = 16;
    const g = cv.getContext("2d");
    g.drawImage(td, base[0] * 16, base[1] * 16, 16, 16, 0, 0, 16, 16);
    if (grp) {
      const im = g.getImageData(0, 0, 16, 16), d = im.data;
      for (let p = 0; p < d.length; p += 4) {
        if (!d[p + 3]) continue;
        const [h, s, l] = hsl(d[p], d[p + 1], d[p + 2]);
        if (s < 0.2 || (h > 8 && h < 48)) continue;
        const o = rgb(h + grp * 85, s, l);
        d[p] = o[0]; d[p + 1] = o[1]; d[p + 2] = o[2];
      }
      g.putImageData(im, 0, 0);
    }
    return cv;
  }

  const CSS = `
#w-root{position:fixed;inset:0;z-index:30;background:#05070b;display:none;flex-direction:column;user-select:none;-webkit-user-select:none;touch-action:none}
#w-root.on{display:flex}
#w-hud{height:44px;flex:none;display:flex;align-items:center;gap:14px;padding:0 70px 0 12px;background:var(--pn);border-bottom:3px solid var(--ln);color:var(--tx);font-weight:800;overflow:hidden}
#w-hud .it{display:flex;align-items:center;gap:6px}
#w-hud .w-ic{flex:none}
#w-vbar{width:clamp(70px,16vw,160px);height:14px;background:#0a0e16;border:2px solid var(--ln);position:relative;overflow:hidden}
#w-vbar i{position:absolute;left:0;top:0;bottom:0;background:linear-gradient(90deg,var(--gn),var(--yl));transition:width .5s}
#w-pips{display:flex;gap:3px}
#w-pips b{width:9px;height:16px;background:var(--yl)}
#w-pips b.off{background:#2a3144}
#w-chips{display:flex;gap:8px;align-items:center;margin-left:auto}
@media(max-width:560px){#w-hud{gap:8px;padding:0 64px 0 8px}#w-vbar{width:40px}#w-vn,#w-clock-ic{display:none}#w-pips b{width:6px}#w-pips{gap:2px}}
#w-exit{position:absolute;right:6px;top:-1px;width:56px;height:56px;z-index:5;display:flex;align-items:center;justify-content:center;padding:0}
#w-ghost{flex:none;position:relative}
#w-stage{flex:1;min-height:0;position:relative;display:flex;align-items:center;justify-content:center;overflow:hidden}
#w-cv{image-rendering:pixelated;image-rendering:crisp-edges;display:block;flex:none}
#w-layer{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.w-bub{position:absolute;transform:translate(-50%,-100%);max-width:200px;background:#fff;color:#10151f;border:3px solid #10151f;padding:5px 9px;font:700 14px/1.25 ui-monospace,Menlo,Consolas,monospace;text-align:center;box-shadow:0 3px 0 rgba(0,0,0,.4);pointer-events:none;z-index:3}
.w-bub::after{content:"";position:absolute;left:50%;bottom:-10px;margin-left:-6px;border:6px solid transparent;border-top:7px solid #10151f}
#w-focus{position:absolute;transform:translate(-50%,-100%);display:none;align-items:center;gap:5px;background:var(--yl);color:#1a1400;border:3px solid #a8861a;padding:3px 8px;font-weight:800;font-size:13px;animation:wbob .7s ease-in-out infinite alternate;z-index:2;white-space:nowrap}
@keyframes wbob{from{margin-top:0}to{margin-top:-5px}}
#w-dock{flex:none;height:80px;display:none;align-items:center;justify-content:space-between;padding:0 12px;background:var(--pn);border-top:3px solid var(--ln)}
#w-dock.on{display:flex}
.wbtn{min-width:56px;min-height:56px;display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:0 16px;font-weight:800;font-size:15px;color:var(--tx);background:var(--pn2);border:3px solid var(--ln);border-radius:6px;box-shadow:0 4px 0 #0a0e16;cursor:pointer;touch-action:manipulation}
.wbtn:active{transform:translateY(3px);box-shadow:0 1px 0 #0a0e16}
.wbtn.pri{background:var(--yl);color:#1a1400;border-color:#a8861a}
.wbtn.dim{opacity:.45}
.wbtn.big{min-width:64px;min-height:64px}
#w-modal{position:fixed;inset:0;z-index:50;background:rgba(7,10,16,.78);display:none;align-items:center;justify-content:center;padding:12px;overflow:auto}
#w-modal.on{display:flex}
#w-mp{background:var(--pn);border:3px solid var(--ln);border-radius:8px;padding:14px;max-width:560px;width:100%;max-height:100%;overflow:auto;box-shadow:0 8px 0 #070a10;color:var(--tx)}
#w-mb{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;margin-top:12px}
#w-fade{position:absolute;inset:0;background:#000;opacity:0;pointer-events:none;z-index:6;transition:opacity .35s}
`;

  const handlers = {}, frames = [], draws = { under: [], over: [] }, reg = new Map();
  const W = (window.World = {
    TW, GW, GH, ROOM, VC, icons: ICONS, icon, shapeSvg, shapeDraw, env: null, active: false, busy: false,
    player: { x: 24.5, y: 13.5, carrying: null }, employees: [], layout: { pods: {}, desks: {} }, onExit: null,
    dom: {}, view: { w: GW * TW, h: GH * TW, s: 1, cx: 0, cy: 0 }
  });
  let st = null, sheets = null, solid = null, stat = null, cv, ctx, keys = {}, path = null, pending = null, tries = 0, focusId = null;
  let time = 0, dark = 0, night = false, empA = 1, raf = 0, last = 0, bubbles = [], modalClose = null, hudState = {};
  const $ = (id) => document.getElementById(id);

  W.registerInteractable = (o) => {
    reg.set(o.id, Object.assign({ radius: 1.5, w: 1, h: 1, solid: false }, o));
    if (o.solid) rebuildSolid();
  };
  W.unregisterInteractable = (id) => { const o = reg.get(id); reg.delete(id); if (o && o.solid) rebuildSolid(); };
  W.moveInteractable = (id, x, y) => { const o = reg.get(id); if (o) { o.x = x; o.y = y; } };
  W.getInteractable = (id) => reg.get(id) || null;
  W.onEvent = (n, f) => { (handlers[n] = handlers[n] || []).push(f); };
  W.emit = (n, p) => (handlers[n] || []).slice().forEach((f) => f(p));
  W.onFrame = (f) => frames.push(f);
  W.onDraw = (f, layer) => draws[layer === "over" ? "over" : "under"].push(f);
  W.setCarry = (it) => { W.player.carrying = it || null; };
  W.toast = (t, k) => {
    const d = document.createElement("div");
    d.className = "toast " + (k || "");
    d.textContent = t;
    $("toasts").appendChild(d);
    setTimeout(() => d.remove(), 2600);
  };
  W.bubble = (x, y, text, ms) => {
    const t = String(text).trim().split(/\s+/).slice(0, 8).join(" ");
    const el = document.createElement("div");
    el.className = "w-bub";
    el.textContent = t;
    W.dom.layer.appendChild(el);
    const b = { x, y, el, until: performance.now() + (ms || 2800) };
    bubbles.push(b);
    placeBubble(b);
    return () => { b.until = 0; };
  };
  W.hud = {
    set(o) {
      Object.assign(hudState, o);
      if (o.day != null) $("w-day").textContent = Math.min(21, o.day) + "/21";
      if (o.V != null) { $("w-vf").style.width = Math.max(0, Math.min(1, o.V)) * 100 + "%"; $("w-vn").textContent = o.V.toFixed(2); }
      if (o.actions != null) $("w-pips").innerHTML = [...Array(8)].map((_, i) => "<b" + (i >= o.actions ? ' class="off"' : "") + "></b>").join("");
      if (o.clock != null) $("w-clock").textContent = o.clock;
    }
  };
  function syncHud() {
    const e = W.env;
    if (!e) return;
    const h = 9 + Math.min(8, 8 - e.actions);
    W.hud.set({ day: e.day, V: e.V, actions: e.actions, clock: String(h).padStart(2, "0") + ":00" });
  }
  W.act = (tool, args) => {
    const e = W.env, r = e.call(tool, args || {});
    syncHud();
    W.emit("env:call", { tool, args: args || {}, result: r });
    if (tool === "advance_day" && r.ok) {
      W.emit("day:end", { day: r.data.closed_day, result: r });
      if (!e.over) nightCycle();
    }
    return r;
  };
  function nightCycle() {
    W.busy = true;
    night = true;
    path = null;
    setTimeout(() => {
      $("w-fade").style.opacity = 1;
      setTimeout(() => {
        night = false;
        dark = 0;
        empA = 1;
        resetEmps();
        syncHud();
        $("w-fade").style.opacity = 0;
        W.busy = false;
        W.emit("day:start", { day: W.env.day });
      }, 400);
    }, 1200);
  }
  W.openModal = (html, buttons) => {
    if (modalClose) modalClose();
    const m = $("w-modal"), body = document.createElement("div"), bar = $("w-mb");
    $("w-mp").firstChild.replaceWith(body);
    let open = true;
    const close = () => { if (!open) return; open = false; m.classList.remove("on"); modalClose = null; };
    const setButtons = (bs) => {
      bar.innerHTML = "";
      (bs || []).forEach((b) => {
        const el = document.createElement("button");
        el.className = "wbtn big" + (b.primary ? " pri" : "");
        el.innerHTML = (b.icon ? icon(b.icon, 24) : "") + (b.label ? "<span>" + b.label + "</span>" : "");
        el.addEventListener("click", () => { const r = b.onClick && b.onClick(close); if (r !== false && !b.keep) close(); });
        bar.appendChild(el);
      });
    };
    body.innerHTML = html;
    setButtons(buttons);
    close.body = body;
    close.setHtml = (h) => (body.innerHTML = h);
    close.setButtons = setButtons;
    modalClose = close;
    m.classList.add("on");
    return close;
  };
  W.modalOpen = () => !!modalClose;

  function rectDist(px, py, o) {
    const dx = Math.max(o.x - px, 0, px - (o.x + o.w)), dy = Math.max(o.y - py, 0, py - (o.y + o.h));
    return Math.hypot(dx, dy);
  }
  W.nearest = () => {
    const p = W.player;
    let best = null, bd = 1e9;
    reg.forEach((o) => {
      if (o.enabled && !o.enabled()) return;
      const d = rectDist(p.x, p.y, o);
      if (d <= o.radius && d < bd) { bd = d; best = o; }
    });
    return best;
  };
  W.use = () => {
    if (W.busy || modalClose) return;
    const o = W.nearest();
    if (o) o.onUse({ id: o.id, player: W.player, world: W, env: W.env });
  };
  function rebuildSolid() {
    solid = base.map((r) => r.slice());
    reg.forEach((o) => {
      if (!o.solid) return;
      for (let y = Math.floor(o.y); y < Math.ceil(o.y + o.h); y++) for (let x = Math.floor(o.x); x < Math.ceil(o.x + o.w); x++) if (solid[y] && x >= 0 && x < GW) solid[y][x] = 1;
    });
  }
  let base = null;
  function buildBase() {
    base = [...Array(GH)].map(() => Array(GW).fill(0));
    const b = (x, y, w, h) => { for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) base[j][i] = 1; };
    b(0, 0, GW, 1); b(0, GH - 1, GW, 1); b(0, 0, 1, GH); b(GW - 1, 0, 1, GH);
    b(10, 0, 1, 6); b(10, 7, 1, 3); b(0, 9, 11, 1);
    b(21, 1, 3, 1);
    b(2, 1, 8, 2);
    b(2, 23, 1, 1); b(41, 23, 1, 1);
  }
  const free = (x, y) => x >= 0 && y >= 0 && x < GW && y < GH && !solid[y][x];
  const canStand = (x, y) => free(Math.floor(x - HB), Math.floor(y - HB)) && free(Math.floor(x + HB), Math.floor(y - HB)) && free(Math.floor(x - HB), Math.floor(y + HB)) && free(Math.floor(x + HB), Math.floor(y + HB));

  function findPath(sx, sy, isGoal, hx, hy) {
    const open = [{ x: sx, y: sy, g: 0, f: 0, p: null }], seen = new Map([[sy * GW + sx, 0]]);
    let n = 0, bestN = open[0], bh = 1e9;
    while (open.length && n++ < 600) {
      let bi = 0;
      for (let i = 1; i < open.length; i++) if (open[i].f < open[bi].f) bi = i;
      const c = open.splice(bi, 1)[0];
      if (isGoal(c.x, c.y)) { bestN = c; bh = -1; break; }
      const h0 = Math.hypot(c.x - hx, c.y - hy);
      if (h0 < bh) { bh = h0; bestN = c; }
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dy) continue;
        const nx = c.x + dx, ny = c.y + dy;
        if (!free(nx, ny)) continue;
        if (dx && dy && (!free(c.x + dx, c.y) || !free(c.x, c.y + dy))) continue;
        const g = c.g + (dx && dy ? 1.414 : 1), k = ny * GW + nx;
        if (seen.has(k) && seen.get(k) <= g) continue;
        seen.set(k, g);
        open.push({ x: nx, y: ny, g, f: g + Math.hypot(nx - hx, ny - hy), p: c });
      }
    }
    const out = [];
    for (let c = bestN; c && c.p; c = c.p) out.push([c.x + 0.5, c.y + 0.5]);
    return out.reverse();
  }
  function nearFree(tx, ty) {
    if (free(tx, ty)) return [tx, ty];
    for (let r = 1; r < 6; r++) for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) if (Math.max(Math.abs(dx), Math.abs(dy)) === r && free(tx + dx, ty + dy)) return [tx + dx, ty + dy];
    return [tx, ty];
  }
  W.walkTo = (x, y, useId) => {
    const p = W.player, sx = Math.floor(p.x), sy = Math.floor(p.y);
    pending = useId || null;
    if (useId) {
      const o = reg.get(useId);
      if (!o) return;
      if (rectDist(p.x, p.y, o) <= Math.min(o.radius, 1.1) && (!o.enabled || o.enabled())) { path = null; W.use2(o); return; }
      const r = Math.max(0.5, Math.min(o.radius * 0.75, 1.1)), cx = o.x + o.w / 2, cy = o.y + o.h / 2;
      path = findPath(sx, sy, (tx, ty) => free(tx, ty) && rectDist(tx + 0.5, ty + 0.5, o) <= r, cx, cy);
    } else {
      const [tx, ty] = nearFree(Math.floor(x), Math.floor(y));
      path = findPath(sx, sy, (a, b) => a === tx && b === ty, tx, ty);
    }
  };
  W.use2 = (o) => { if (!W.busy && !modalClose) o.onUse({ id: o.id, player: W.player, world: W, env: W.env }); };

  function empInter(e) {
    return { id: "emp:" + e.id, x: e.x, y: e.y, label: e.name.split(" ")[0], icon: "mic", radius: 1.5, onUse: () => W.emit("talk", { id: e.id }) };
  }
  function buildEmps() {
    const list = W.env.w.employees, cnt = {};
    W.employees = list.map((e, i) => {
      const k = (cnt[e.dept] = (cnt[e.dept] || 0));
      cnt[e.dept]++;
      const di = Math.max(0, DEPTS.indexOf(e.dept)), o = POD[e.dept] || POD.Engineering;
      const dx = o[0] + (k % 4) * 3, dy = o[1] + Math.floor(k / 4) * 2;
      const m = { id: e.id, name: e.name, dept: e.dept, col: DCOL[di], spr: sprite(sheets[0], BASES[i % BASES.length], Math.floor(i / BASES.length)), k, desk: { x: dx, y: dy }, home: { x: dx, y: dy + 1 }, x: dx, y: dy + 1, dir: 1, path: [], wait: 2 + Math.random() * 9, state: "desk", moving: false, ph: Math.random() * 6 };
      W.layout.desks[e.id] = { x: dx, y: dy, ex: dx, ey: dy + 1 };
      return m;
    });
    Object.keys(POD).forEach((d) => {
      const o = POD[d];
      W.layout.pods[d] = { dept: d, ox: o[0], oy: o[1], mat: { x: o[0] + 5, y: o[1] + 3 }, col: DCOL[DEPTS.indexOf(d)] };
    });
  }
  function resetEmps() {
    W.employees.forEach((e) => { e.x = e.home.x; e.y = e.home.y; e.path = []; e.state = "desk"; e.wait = 2 + Math.random() * 9; e.moving = false; syncEmp(e); });
  }
  function syncEmp(e) { const o = reg.get("emp:" + e.id); if (o) W.moveInteractable("emp:" + e.id, e.x, e.y); }
  W.empAt = (id) => W.employees.find((e) => e.id === id) || null;

  function stepEmps(dt) {
    const away = W.employees.filter((e) => e.state !== "desk").length, near = W.nearest();
    W.employees.forEach((e) => {
      const held = near && near.id === "emp:" + e.id;
      if (e.path.length) {
        if (held) { e.moving = false; return; }
        const t = e.path[0], dx = t[0] - 0.5 - e.x, dy = t[1] - 0.5 - e.y, d = Math.hypot(dx, dy), s = 2.6 * dt;
        e.moving = true;
        if (Math.abs(dx) > 0.01) e.dir = dx > 0 ? 1 : -1;
        if (d <= s) { e.x = t[0] - 0.5; e.y = t[1] - 0.5; e.path.shift(); } else { e.x += (dx / d) * s; e.y += (dy / d) * s; }
        syncEmp(e);
        if (!e.path.length) { e.moving = false; e.state = e.state === "go" ? "coffee" : "desk"; e.wait = e.state === "coffee" ? 3 + Math.random() * 5 : 4 + Math.random() * 12; }
        return;
      }
      e.moving = false;
      e.wait -= dt;
      if (e.wait > 0 || night || held) return;
      if (e.state === "desk") {
        if (away >= 4 || Math.random() > 0.5) { e.wait = 3 + Math.random() * 8; return; }
        const c = COFFEE[Math.floor(Math.random() * COFFEE.length)];
        e.path = findPath(Math.floor(e.x), Math.floor(e.y), (a, b) => a === c[0] && b === c[1], c[0], c[1]);
        e.state = "go";
      } else {
        e.path = findPath(Math.floor(e.x + 0.5), Math.floor(e.y + 0.5), (a, b) => a === e.home.x && b === e.home.y, e.home.x, e.home.y);
        e.state = "back";
      }
      if (!e.path.length) { e.state = "desk"; e.wait = 5; }
    });
  }

  function stepPlayer(dt) {
    const p = W.player;
    let mx = (keys.d || keys.ArrowRight ? 1 : 0) - (keys.a || keys.ArrowLeft ? 1 : 0), my = (keys.s || keys.ArrowDown ? 1 : 0) - (keys.w || keys.ArrowUp ? 1 : 0);
    p.moving = false;
    if (W.busy || modalClose) return;
    if (mx || my) { path = null; pending = null; }
    else if (path && path.length) {
      const t = path[0], dx = t[0] - p.x, dy = t[1] - p.y, d = Math.hypot(dx, dy);
      if (d < 0.1) path.shift(); else { mx = dx / d; my = dy / d; }
      if (!path.length) {
        path = null;
        const o = pending && reg.get(pending);
        if (o && rectDist(p.x, p.y, o) <= o.radius) { pending = null; W.use2(o); }
        else if (o && tries++ < 3) W.walkTo(0, 0, pending);
        else pending = null;
        tries = path ? tries : 0;
      }
    }
    if (!mx && !my) return;
    const l = Math.hypot(mx, my), s = SPD * dt * (p.carrying ? 0.8 : 1);
    mx = (mx / l) * s; my = (my / l) * s;
    if (canStand(p.x + mx, p.y)) p.x += mx;
    if (canStand(p.x, p.y + my)) p.y += my;
    if (Math.abs(mx) > 0.001) p.dir = mx > 0 ? 1 : -1;
    p.moving = true;
  }

  function buildStatic() {
    const c = document.createElement("canvas");
    c.width = GW * TW; c.height = GH * TW;
    const g = c.getContext("2d");
    g.imageSmoothingEnabled = false;
    const R = (x, y, w, h, col) => { g.fillStyle = col; g.fillRect(x, y, w, h); };
    const T = (x, y, w, h, col) => R(x * TW, y * TW, w * TW, h * TW, col);
    R(0, 0, c.width, c.height, "#1a1f2b");
    for (let y = 1; y < GH - 1; y++) for (let x = 1; x < GW - 1; x++) R(x * TW, y * TW, TW, TW, (x + y) % 2 ? "#7d8aa0" : "#75829a");
    for (let y = 1; y < 9; y++) for (let x = 1; x < 10; x++) R(x * TW, y * TW, TW, TW, (x + y) % 2 ? "#2b3140" : "#272c3a");
    for (let y = 6; y < 12; y++) for (let x = 37; x < 43; x++) R(x * TW, y * TW, TW, TW, (x + y) % 2 ? "#9a7a52" : "#92724b");
    const wall = (x, y, w, h) => {
      R(x * TW, y * TW, w * TW, h * TW, "#2c3447");
      R(x * TW, y * TW, w * TW, 3, "#47536d");
      for (let i = 0; i < w * TW; i += 8) R(x * TW + i, (y + h) * TW - 2, 1, 2, "#1a1f2b");
    };
    wall(0, 0, GW, 1); wall(0, GH - 1, GW, 1); wall(0, 0, 1, GH); wall(GW - 1, 0, 1, GH);
    wall(10, 0, 1, 6); wall(10, 7, 1, 3); wall(0, 9, 11, 1);
    Object.keys(POD).forEach((d) => {
      const o = POD[d], col = DCOL[DEPTS.indexOf(d)];
      g.globalAlpha = 0.14;
      T(o[0] - 1, o[1] - 1, 13, 8, col);
      g.globalAlpha = 1;
      R((o[0] + 5) * TW + 1, (o[1] + 3) * TW + 3, 14, 10, col);
      R((o[0] + 5) * TW + 3, (o[1] + 3) * TW + 5, 10, 6, "rgba(255,255,255,.28)");
    });
    W.employees.forEach((e) => {
      const x = e.desk.x * TW, y = e.desk.y * TW;
      R(x, y + 2, 32, 11, "#9a7a52");
      R(x, y + 2, 32, 2, "#b99668");
      R(x, y + 13, 32, 2, "#6e5336");
      R(x + 4, y + 3, 10, 7, "#222c3a");
      R(x + 5, y + 4, 8, 4, "#7cf0c8");
      R(x + 17, y + 8, 9, 3, "#d8d4c6");
      R(e.home.x * TW + 4, e.home.y * TW + 9, 8, 6, "#3a3f50");
    });
    for (let i = 0; i < 4; i++) {
      const sx = (2 + i * 2) * TW;
      for (let j = 0; j < 2; j++) {
        g.drawImage(sheets[1], 14 * 17, (16 + j) * 17, 16, 16, sx, (1 + j) * TW, 16, 16);
        g.drawImage(sheets[1], 15 * 17, (16 + j) * 17, 16, 16, sx + TW, (1 + j) * TW, 16, 16);
      }
      R(sx + 6, 2 * TW + 4, 2, 2, i % 2 ? "#35fb9a" : "#ff5a5a");
      R(sx + 22, 2 * TW + 4, 2, 2, i % 2 ? "#ff5a5a" : "#35fb9a");
    }
    const bx = ROOM.server_term[0] * TW, by = ROOM.server_term[1] * TW;
    R(bx, by + 2, 32, 11, "#4a5266"); R(bx + 4, by + 3, 10, 7, "#10141c"); R(bx + 5, by + 4, 8, 4, "#35fb9a");
    R(21 * TW, TW + 1, 48, 14, "#10141c"); R(21 * TW + 3, TW + 3, 42, 9, "#2a6f98"); R(21 * TW + 6, TW + 5, 10, 2, "#9fe3ff");
    R(15 * TW + 2, TW + 2, 12, 12, "#e8e4d8"); R(15 * TW + 3, TW + 3, 10, 10, "#fff"); R(15 * TW + 8, TW + 4, 1, 5, "#10141c"); R(15 * TW + 8, TW + 8, 4, 1, "#10141c");
    const px = ROOM.desk_pc[0] * TW, py = ROOM.desk_pc[1] * TW;
    R(px, py + 2, 32, 11, "#a98456"); R(px, py + 2, 32, 2, "#c9a574"); R(px + 4, py + 3, 12, 8, "#222c3a"); R(px + 5, py + 4, 10, 5, "#ffd23f"); R(px + 19, py + 8, 9, 3, "#d8d4c6");
    const qx = ROOM.printer[0] * TW, qy = ROOM.printer[1] * TW;
    R(qx, qy + 3, 32, 11, "#cfd3dc"); R(qx, qy + 3, 32, 3, "#eef0f5"); R(qx + 4, qy + 8, 24, 3, "#4a5266"); R(qx + 22, qy + 5, 4, 2, "#35fb9a"); R(qx + 6, qy, 20, 4, "#fff");
    const cx = ROOM.coffee[0] * TW, cy = ROOM.coffee[1] * TW;
    R(cx, cy + 2, 32, 12, "#4a3a2e"); R(cx + 4, cy + 4, 8, 8, "#d8d4c6"); R(cx + 18, cy + 4, 8, 8, "#c0392b"); R(cx + 20, cy + 6, 4, 2, "#ffd23f");
    const dx = ROOM.red_door[0] * TW, dy = ROOM.red_door[1] * TW;
    R(dx, dy, 16, 16, "#a42a2a"); R(dx + 2, dy + 2, 12, 12, "#d63c3c"); R(dx + 10, dy + 8, 2, 2, "#ffd23f");
    const kx = ROOM.case_board[0] * TW, ky = ROOM.case_board[1] * TW;
    R(kx, ky, 16, 16, "#6e5336"); R(kx + 2, ky + 2, 12, 12, "#c9a574"); R(kx + 4, ky + 4, 3, 3, "#fff"); R(kx + 9, ky + 6, 3, 3, "#fff"); R(kx + 5, ky + 10, 4, 2, "#ff5a5a");
    const lx = ROOM.bell[0] * TW, ly = ROOM.bell[1] * TW;
    R(lx + 2, ly + 10, 12, 4, "#6e5336"); R(lx + 4, ly + 4, 8, 6, "#ffd23f"); R(lx + 3, ly + 8, 10, 2, "#c9a21f"); R(lx + 7, ly + 2, 2, 2, "#ffd23f");
    [[2, 23], [41, 23]].forEach((p) => g.drawImage(sheets[1], 16 * 17, 0, 16, 16, p[0] * TW, p[1] * TW, 16, 16));
    stat = c;
  }

  function placeBubble(b) {
    const v = W.view, cvr = cv, sc = cvr.clientWidth / v.w;
    b.el.style.left = cvr.offsetLeft + (b.x * TW - v.cx) * sc + "px";
    b.el.style.top = cvr.offsetTop + (b.y * TW - v.cy) * sc + "px";
  }
  function layoutView() {
    const st2 = $("w-stage"), cw = st2.clientWidth, ch = st2.clientHeight, v = W.view;
    if (!cw || !ch) return;
    const fit = Math.min(cw / (GW * TW), ch / (GH * TW));
    if (fit >= 1.4) { v.w = GW * TW; v.h = GH * TW; v.s = fit; v.follow = false; }
    else { v.s = 2; v.w = Math.ceil(cw / 2); v.h = Math.ceil(ch / 2); v.follow = true; }
    cv.width = v.w; cv.height = v.h;
    cv.style.width = v.w * v.s + "px"; cv.style.height = v.h * v.s + "px";
    ctx.imageSmoothingEnabled = false;
  }
  function camera() {
    const v = W.view, p = W.player;
    if (!v.follow) { v.cx = 0; v.cy = 0; return; }
    const mw = GW * TW, mh = GH * TW;
    v.cx = v.w >= mw ? (mw - v.w) / 2 : Math.max(0, Math.min(mw - v.w, p.x * TW - v.w / 2));
    v.cy = v.h >= mh ? (mh - v.h) / 2 : Math.max(0, Math.min(mh - v.h, p.y * TW - v.h / 2));
  }
  function draw() {
    const v = W.view, p = W.player;
    ctx.fillStyle = "#05070b";
    ctx.fillRect(0, 0, v.w, v.h);
    ctx.save();
    ctx.translate(-Math.round(v.cx), -Math.round(v.cy));
    ctx.drawImage(stat, 0, 0);
    draws.under.forEach((f) => f(ctx, W));
    const ents = W.employees.map((e) => ({ y: e.y, e })).concat([{ y: p.y - 0.5, pl: 1 }]).sort((a, b) => a.y - b.y);
    ents.forEach((o) => {
      if (o.pl) return drawPlayer();
      if (empA < 0.02) return;
      const e = o.e, px = Math.round(e.x * TW), py = Math.round(e.y * TW), bob = e.moving ? Math.floor((time + e.ph) * 8) % 2 : 0;
      ctx.globalAlpha = empA;
      ctx.fillStyle = "rgba(0,0,0,.3)";
      ctx.fillRect(px + 3, py + 14, 10, 2);
      ctx.fillStyle = e.col;
      ctx.fillRect(px + 4, py + 15, 8, 1);
      blit(e.spr, px, py - bob, e.dir < 0);
      ctx.globalAlpha = 1;
    });
    draws.over.forEach((f) => f(ctx, W));
    if (dark > 0.01) { ctx.fillStyle = "rgba(8,12,44," + dark + ")"; ctx.fillRect(0, 0, GW * TW, GH * TW); }
    ctx.restore();
  }
  function blit(img, x, y, flip) {
    if (flip) { ctx.save(); ctx.translate(x + 16, y); ctx.scale(-1, 1); ctx.drawImage(img, 0, 0); ctx.restore(); }
    else ctx.drawImage(img, x, y);
  }
  function drawPlayer() {
    const p = W.player, px = Math.round(p.x * TW - 8), py = Math.round(p.y * TW - 12), bob = p.moving ? Math.floor(time * 10) % 2 : 0;
    ctx.fillStyle = "rgba(0,0,0,.35)";
    ctx.fillRect(px + 3, py + 14, 10, 2);
    ctx.fillStyle = "#ffd23f";
    ctx.fillRect(px + 4, py + 15, 8, 1);
    blit(W.playerSpr, px, py - bob, p.dir < 0);
    const yb = py - 5 - Math.floor(Math.sin(time * 5) + 1);
    ctx.fillStyle = "#ffd23f";
    ctx.fillRect(px + 6, yb, 4, 1); ctx.fillRect(px + 7, yb + 1, 2, 1);
    if (p.carrying) {
      const l = p.carrying.data && p.carrying.data.label, qx = px + 3, qy = py - 13 - bob;
      ctx.fillStyle = "#fff";
      ctx.fillRect(qx, qy, 10, 12);
      ctx.strokeStyle = "#10151f";
      ctx.strokeRect(qx + 0.5, qy + 0.5, 9, 11);
      if (l) shapeDraw(ctx, l, qx + 2, qy + 3, 6);
    }
  }

  function refreshFocus() {
    const o = W.nearest(), f = $("w-focus"), id = o ? o.id : null;
    if (id !== focusId) {
      focusId = id;
      f.style.display = o ? "flex" : "none";
      if (o) f.innerHTML = icon(o.icon, 18) + "<span>" + (o.label || "").split(/\s+/).slice(0, 2).join(" ") + "</span>";
      $("w-use").classList.toggle("dim", !o);
    }
    if (o) {
      const v = W.view, sc = cv.clientWidth / v.w, ax = (o.x + o.w / 2) * TW, ay = o.y * TW;
      f.style.left = cv.offsetLeft + (ax - v.cx) * sc + "px";
      f.style.top = cv.offsetTop + (ay - v.cy - 4) * sc + "px";
    }
  }
  function loop(t) {
    if (!W.active) { raf = 0; return; }
    const dt = Math.min(0.05, (t - last) / 1000 || 0);
    last = t;
    time += dt;
    if (night) { dark += (0.55 - dark) * Math.min(1, dt * 2.5); empA = Math.max(0, 1 - dark / 0.4); }
    stepPlayer(dt);
    stepEmps(dt);
    frames.forEach((f) => f(dt));
    camera();
    draw();
    refreshFocus();
    const now = performance.now();
    bubbles = bubbles.filter((b) => { if (now > b.until) { b.el.remove(); return false; } placeBubble(b); return true; });
    raf = requestAnimationFrame(loop);
  }

  function ptr(e) {
    const r = cv.getBoundingClientRect(), v = W.view;
    return [((e.clientX - r.left) / r.width) * v.w + v.cx, ((e.clientY - r.top) / r.height) * v.h + v.cy];
  }
  function onTap(e) {
    if (W.busy || modalClose) return;
    const [px, py] = ptr(e), tx = px / TW, ty = py / TW;
    let best = null, bd = 0.8;
    reg.forEach((o) => {
      if (o.enabled && !o.enabled()) return;
      const d = rectDist(tx, ty, o);
      if (d < bd || (d === bd && best && o.id.indexOf("emp:") === 0)) { bd = d; best = o; }
    });
    if (best) W.walkTo(0, 0, best.id);
    else { pending = null; W.walkTo(tx, ty); }
  }
  function onKey(e) {
    if (!W.active) return;
    if (e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName)) { if (e.key === "Escape" && modalClose) modalClose(); return; }
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (e.type === "keyup") { keys[k] = false; return; }
    if (/^(Arrow|\s)/.test(k) || k === " ") e.preventDefault();
    keys[k] = true;
    if (k === "Escape") { if (modalClose) modalClose(); }
    else if (k === "e" || k === " ") W.use();
    else if (k === "b" && !modalClose && !W.busy) W.emit("bell");
    else if (k === "q" && !modalClose) { W.setCarry(null); W.emit("carry:drop"); }
  }

  function buildDom() {
    if ($("w-root")) return;
    const s = document.createElement("style");
    s.textContent = CSS;
    document.head.appendChild(s);
    const r = document.createElement("div");
    r.id = "w-root";
    r.innerHTML = '<div id="w-hud"><span class="it">' + icon("calendar", 20) + '<span id="w-day">1/21</span></span><span class="it">' + icon("coin", 20) + '<span id="w-vbar"><i id="w-vf" style="width:100%"></i></span><span id="w-vn">1.00</span></span><span class="it" id="w-pips"></span><span class="it">' + icon("clock", 20) + '<span id="w-clock">09:00</span></span><span id="w-chips"></span><button class="wbtn" id="w-exit">' + icon("x", 28) + '</button></div><div id="w-ghost"></div><div id="w-stage"><canvas id="w-cv"></canvas><div id="w-layer"><div id="w-focus"></div></div><div id="w-fade"></div></div><div id="w-dock"><button class="wbtn big" id="w-bell">' + icon("bell", 30) + '</button><button class="wbtn big pri dim" id="w-use" style="min-width:120px;min-height:64px">' + icon("check", 30) + '<span>USE</span></button></div>';
    document.body.appendChild(r);
    const m = document.createElement("div");
    m.id = "w-modal";
    m.innerHTML = '<div id="w-mp"><div></div><div id="w-mb"></div></div>';
    document.body.appendChild(m);
    cv = $("w-cv");
    ctx = cv.getContext("2d");
    W.dom = { root: r, layer: $("w-layer"), ghost: $("w-ghost"), chips: $("w-chips"), stage: $("w-stage"), canvas: cv };
    cv.addEventListener("pointerdown", (e) => { e.preventDefault(); onTap(e); });
    $("w-use").addEventListener("click", () => W.use());
    $("w-bell").addEventListener("click", () => { if (!W.busy && !modalClose) W.emit("bell"); });
    $("w-exit").addEventListener("click", () => W.stop());
    document.addEventListener("keydown", onKey);
    document.addEventListener("keyup", onKey);
    window.addEventListener("resize", () => { if (W.active) { layoutView(); toggleDock(); } });
    window.addEventListener("blur", () => (keys = {}));
  }
  function toggleDock() {
    const coarse = window.matchMedia && matchMedia("(pointer:coarse)").matches;
    $("w-dock").classList.toggle("on", coarse || window.innerWidth < 800);
    layoutView();
  }

  W.reset = () => {
    Object.keys(handlers).forEach((k) => delete handlers[k]);
    frames.length = 0; draws.under.length = 0; draws.over.length = 0; reg.clear();
    bubbles.forEach((b) => b.el.remove()); bubbles = [];
    if (modalClose) modalClose();
    keys = {}; path = null; pending = null; night = false; dark = 0; empA = 1; focusId = null; W.busy = false;
    W.layout = { pods: {}, desks: {} };
    W.player.carrying = null;
  };
  W.start = (seed, feats) => {
    if (!W.env) return;
    buildDom();
    W.reset();
    buildBase();
    solid = base.map((r) => r.slice());
    buildEmps();
    W.playerSpr = W.playerSpr || sprite(sheets[0], [0, 7], 3);
    buildStatic();
    const ps = ROOM.player_start;
    Object.assign(W.player, { x: ps[0] + 0.5, y: ps[1] + 0.5, dir: 1, moving: false });
    const defs = [
      ["desk_pc", "monitor", "Desk PC", 2, 1, true], ["server_term", "rack", "Server", 2, 1, true], ["feed_tv", "tv", "Leak TV", 1, 1, false],
      ["printer", "printer", "Printer", 2, 1, true], ["bell", "bell", "Bell", 1, 1, false], ["red_door", "door", "Accuse", 1, 1, false], ["case_board", "pin", "Case board", 1, 1, true]
    ];
    defs.forEach((d) => {
      const rc = ROOM[d[0]];
      W.registerInteractable({ id: d[0], x: rc[0], y: rc[1], w: d[3], h: d[4], solid: d[5], label: d[2], icon: d[1], onUse: () => W.emit("use:" + d[0]) });
    });
    W.registerInteractable({ id: "coffee", x: ROOM.coffee[0], y: ROOM.coffee[1], w: 2, h: 1, solid: true, label: "Coffee", icon: "coffee", onUse: () => W.toast("Fresh coffee") });
    W.employees.forEach((e) => W.registerInteractable(empInter(e)));
    rebuildSolid();
    W.active = true;
    $("w-root").classList.add("on");
    toggleDock();
    syncHud();
    (feats || ["talk", "desk", "carry"]).forEach((n) => { const f = window["Feat_" + n]; if (f && f.init) f.init(W); });
    W.emit("mode:enter", { seed });
    W.emit("day:start", { day: W.env.day });
    last = performance.now();
    if (!raf) raf = requestAnimationFrame(loop);
  };
  W.stop = () => {
    W.active = false;
    if (modalClose) modalClose();
    const r = $("w-root");
    if (r) r.classList.remove("on");
    if (W.onExit) W.onExit();
  };
  W.setSheets = (a, b) => { sheets = [a, b]; };
})();
