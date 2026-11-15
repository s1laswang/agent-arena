(function () {
  const TW = 16, GW = 44, GH = 26;
  const DEPT_COL = ["#4aa3ff", "#ffc247", "#ff6b6b", "#b17cff", "#4fd6a0"];
  const BASES = [[0, 7], [1, 7], [2, 7], [3, 7], [4, 7], [0, 8], [1, 8], [2, 8], [3, 8], [4, 8], [4, 9]];
  const LANES = [5, 9, 13, 17, 21, 23];
  const DOORY = { server: 5, meet: 14, coffee: 21 };
  const R = window.Eng.rng;

  function load(src) {
    return new Promise((res) => {
      const i = new Image();
      i.onload = () => res(i);
      i.src = src;
    });
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
    h = ((h % 360) + 360) % 360 / 360;
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
    const f = (t) => {
      t = (t + 1) % 1;
      return t < 1 / 6 ? p + (q - p) * 6 * t : t < 1 / 2 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p;
    };
    return [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
  }

  class Office {
    constructor(canvas, sheets) {
      this.cv = canvas;
      canvas.width = GW * TW;
      canvas.height = GH * TW;
      this.ctx = canvas.getContext("2d");
      this.ctx.imageSmoothingEnabled = false;
      this.td = sheets[0];
      this.ri = sheets[1];
      this.emps = [];
      this.byId = {};
      this.badges = {};
      this.rings = {};
      this.dim = new Set();
      this.selected = null;
      this.hover = null;
      this.floaters = [];
      this.parts = [];
      this.shake = 0;
      this.night = false;
      this.dark = 0;
      this.time = 0;
      this.hour = 9;
      this.onSelect = null;
      this.spotId = null;
      this.stay = new Set();
      this.rn = R(7);
      this.buildStatic();
      canvas.addEventListener("pointerdown", (e) => this.click(e));
      canvas.addEventListener("pointermove", (e) => (this.hover = this.hit(e)));
      canvas.addEventListener("pointerleave", () => (this.hover = null));
    }
    tile(sheet, c, r, x, y, ctx, flip) {
      const sx = sheet === this.ri ? c * 17 : c * 16, sy = sheet === this.ri ? r * 17 : r * 16;
      ctx = ctx || this.ctx;
      if (flip) {
        ctx.save();
        ctx.translate(x + TW, y);
        ctx.scale(-1, 1);
        ctx.drawImage(sheet, sx, sy, 16, 16, 0, 0, 16, 16);
        ctx.restore();
      } else ctx.drawImage(sheet, sx, sy, 16, 16, x, y, 16, 16);
    }
    buildStatic() {
      const c = document.createElement("canvas");
      c.width = GW * TW;
      c.height = GH * TW;
      const g = c.getContext("2d");
      g.imageSmoothingEnabled = false;
      const fill = (x, y, w, h, a, b) => {
        for (let i = 0; i < w; i++) for (let j = 0; j < h; j++) {
          g.fillStyle = (i + j) % 2 ? a : b;
          g.fillRect((x + i) * TW, (y + j) * TW, TW, TW);
        }
      };
      g.fillStyle = "#1a1f2b";
      g.fillRect(0, 0, c.width, c.height);
      fill(1, 1, 27, 24, "#7d8aa0", "#75829a");
      fill(29, 1, 14, 8, "#2b3140", "#272c3a");
      fill(29, 10, 14, 8, "#9a7a52", "#92724b");
      fill(29, 19, 14, 6, "#c9c2b0", "#bfb8a6");
      g.fillStyle = "rgba(255,255,255,0.05)";
      for (let y = 1; y < 25; y += 4) g.fillRect(TW, (y + 2) * TW, 26 * TW, 2 * TW);
      const wall = (x, y, w, h) => {
        g.fillStyle = "#2c3447";
        g.fillRect(x * TW, y * TW, w * TW, h * TW);
        g.fillStyle = "#47536d";
        g.fillRect(x * TW, y * TW, w * TW, 3);
        g.fillStyle = "#1a1f2b";
        for (let i = 0; i < w * TW; i += 8) g.fillRect(x * TW + i, y * TW + h * TW - 2, 1, 2);
      };
      wall(0, 0, GW, 1);
      wall(0, 25, 14, 1);
      wall(15, 25, 29, 1);
      wall(0, 0, 1, GH);
      wall(43, 0, 1, GH);
      wall(28, 0, 1, 4);
      wall(28, 6, 1, 7);
      wall(28, 15, 1, 6);
      wall(28, 23, 1, 3);
      wall(28, 9, 15, 1);
      wall(28, 18, 15, 1);
      for (let i = 0; i < 2; i++) this.tile(this.td, 9 + i, 1, 14 * TW + i * 0, 25 * TW - 0, g);
      g.fillStyle = "#c58a3a";
      g.fillRect(14 * TW, 25 * TW, TW, 4);
      for (let i = 0; i < 40; i++) {
        const cx = 3 + 3 * (i % 8), cy = 4 + 4 * Math.floor(i / 8);
        this.tile(this.ri, 4, 4, cx * TW, (cy - 1) * TW, g);
        this.tile(this.ri, 5, 4, (cx + 1) * TW, (cy - 1) * TW, g);
        g.fillStyle = "#222c3a";
        g.fillRect(cx * TW + 3, (cy - 1) * TW + 2, 8, 6);
        g.fillStyle = "#7cf0c8";
        g.fillRect(cx * TW + 4, (cy - 1) * TW + 3, 6, 3);
        this.tile(this.ri, 2, 2, cx * TW, cy * TW, g);
      }
      for (let x = 30; x <= 41; x += 2) {
        this.tile(this.ri, 14, 16, x * TW, 1 * TW, g);
        this.tile(this.ri, 14, 17, x * TW, 2 * TW, g);
        this.tile(this.ri, 15, 16, (x + 1) * TW, 1 * TW, g);
        this.tile(this.ri, 15, 17, (x + 1) * TW, 2 * TW, g);
      }
      for (let x = 30; x < 42; x++) {
        g.fillStyle = (x % 2) ? "#35fb9a" : "#ff5a5a";
        g.fillRect(x * TW + 6, 3 * TW + 4, 2, 2);
      }
      for (let j = 0; j < 2; j++) for (let i = 0; i < 3; i++) {
        this.tile(this.ri, 7 + i, 9 + j, (33 + i * 2) * TW, (12 + j) * TW, g);
        this.tile(this.ri, 7 + i, 9 + j, (34 + i * 2) * TW, (12 + j) * TW, g);
      }
      for (let i = 0; i < 6; i++) {
        this.tile(this.ri, 2, 2, (33 + i) * TW, 11 * TW, g);
        this.tile(this.ri, 2, 2, (33 + i) * TW, 15 * TW, g);
      }
      for (let i = 0; i < 12; i++) this.tile(this.ri, i % 7, 12, (30 + i) * TW, 19 * TW, g);
      this.tile(this.ri, 16, 0, 2 * TW, 1 * TW, g);
      this.tile(this.ri, 17, 0, 26 * TW, 1 * TW, g);
      this.tile(this.ri, 16, 0, 2 * TW, 23 * TW, g);
      this.tile(this.ri, 17, 0, 42 * TW, 24 * TW, g);
      this.tile(this.ri, 16, 0, 42 * TW, 10 * TW, g);
      g.fillStyle = "#e8e4d8";
      g.font = "bold 8px monospace";
      g.fillText("SERVER ROOM", 30 * TW + 2, 8 * TW + 8);
      g.fillText("MEETING", 30 * TW + 2, 17 * TW + 8);
      g.fillText("COFFEE", 30 * TW + 2, 24 * TW + 8);
      this.stat = c;
    }
    setEmployees(list, depts) {
      this.emps = list.map((e, i) => {
        const base = BASES[i % BASES.length], grp = Math.floor(i / BASES.length);
        const cv = document.createElement("canvas");
        cv.width = cv.height = 16;
        const g = cv.getContext("2d");
        this.tile(this.td, base[0], base[1], 0, 0, g);
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
        const di = depts.indexOf(e.dept);
        const seat = { x: 3 + 3 * (i % 8), y: 4 + 4 * Math.floor(i / 8) };
        return {
          id: e.id, name: e.name, dept: e.dept, col: DEPT_COL[di % 5], spr: cv, i, seat,
          x: 14, y: 26.5, path: [], wait: Math.random() * 2, vis: false, dir: 1, at: "out", moving: false, ph: Math.random() * 6
        };
      });
      this.byId = {};
      this.emps.forEach((e) => (this.byId[e.id] = e));
      this.clearMarks();
    }
    clearMarks() {
      this.badges = {};
      this.rings = {};
      this.dim = new Set();
      this.selected = null;
    }
    lane(y) {
      if (y >= 22) return 23;
      return LANES.find((l) => l >= y) || 23;
    }
    gap(x) {
      let b = 2;
      for (let g = 2; g <= 26; g += 3) if (Math.abs(g - x) < Math.abs(b - x)) b = g;
      return b;
    }
    route(e, kind, tgt) {
      const p = [];
      const inRoom = e.x >= 28.5;
      let la = 0;
      if (inRoom) {
        const dy = e.at === "server" ? DOORY.server : e.at === "meet" ? DOORY.meet : DOORY.coffee;
        p.push([e.x, dy], [27, dy]);
      } else {
        la = e.y >= 26 ? 23 : this.lane(Math.round(e.y));
        if (e.y >= 26) { p.push([e.x, 23]); }
        else p.push([e.x, la]);
      }
      let room = null;
      if (kind === "seat" || kind === "desk") {
        const lb = this.lane(tgt.y + 1);
        if (inRoom) p.push([27, lb]);
        else { const gx = this.gap(tgt.x); p.push([gx, la], [gx, lb]); }
        p.push([tgt.x, lb], [tgt.x, tgt.y]);
      } else if (kind === "exit") {
        if (inRoom) p.push([27, 23], [14, 23]);
        else { const gx = this.gap(e.x); p.push([gx, la], [gx, 23], [14, 23]); }
        p.push([14, 26.5]);
      } else {
        room = kind;
        const dy = DOORY[kind];
        if (!inRoom) p.push([27, la]);
        p.push([27, dy], [30, dy], [tgt.x, dy], [tgt.x, tgt.y]);
      }
      e.path = p;
      e.dest = room || kind;
      e.at = "moving";
      e.next = kind === "exit" ? "out" : room || "desk";
    }
    seatRoute(e) { this.route(e, "seat", e.seat); }
    randomSpot(kind) {
      const r = Math.random;
      if (kind === "coffee") return { x: 30 + Math.floor(r() * 12), y: 20 + Math.floor(r() * 4) };
      if (kind === "meet") return { x: 33 + Math.floor(r() * 6), y: r() < 0.5 ? 11 : 15 };
      return { x: 30 + Math.floor(r() * 12), y: 5 + Math.floor(r() * 3) };
    }
    setNight(n, instant) {
      this.night = n;
      if (instant) this.dark = n ? 0.55 : 0;
      this.emps.forEach((e) => {
        if (n) {
          if (this.stay.has(e.id)) {
            this.route(e, "server", this.randomSpot("server"));
            e.wait = 3 + Math.random() * 2;
          } else if (e.vis) {
            e.wait = Math.random() * 1.2;
            e.leaving = true;
          }
        } else if (instant) {
          e.leaving = false;
          e.vis = true;
          e.x = e.seat.x; e.y = e.seat.y;
          e.path = []; e.at = "desk"; e.wait = Math.random() * 4;
        } else {
          e.leaving = false;
          if (!e.vis) {
            e.wait = Math.random() * 2.2;
            e.arriving = true;
          } else {
            this.seatRoute(e);
          }
        }
      });
      this.stay.clear();
    }
    sneak(ids) { ids.forEach((i) => this.stay.add(i)); }
    update(dt) {
      this.time += dt;
      this.dark += ((this.night ? 0.55 : 0) - this.dark) * Math.min(1, dt * 2.5);
      if (!this.night) this.hour = Math.min(17.9, 9 + (this.time % 400) / 45);
      this.shake = Math.max(0, this.shake - dt * 14);
      this.floaters.forEach((f) => { f.life -= dt; f.y -= dt * 12; });
      this.floaters = this.floaters.filter((f) => f.life > 0);
      this.parts.forEach((p) => { p.life -= dt; p.x += p.vx * dt; p.y += p.vy * dt; p.vy += 60 * dt; });
      this.parts = this.parts.filter((p) => p.life > 0);
      this.emps.forEach((e) => {
        if (e.path.length) {
          const t = e.path[0], dx = t[0] - e.x, dy = t[1] - e.y, d = Math.hypot(dx, dy), s = 4.4 * dt;
          e.moving = true;
          if (Math.abs(dx) > 0.01) e.dir = dx > 0 ? 1 : -1;
          if (d <= s) { e.x = t[0]; e.y = t[1]; e.path.shift(); } else { e.x += (dx / d) * s; e.y += (dy / d) * s; }
          if (!e.path.length) {
            e.moving = false;
            e.at = e.next;
            e.wait = 1.5 + Math.random() * 5;
            if (e.at === "out") e.vis = false;
          }
          return;
        }
        e.moving = false;
        e.wait -= dt;
        if (e.wait > 0) return;
        if (e.arriving) {
          e.arriving = false;
          e.vis = true;
          e.x = 14; e.y = 26.5;
          this.seatRoute(e);
          return;
        }
        if (!e.vis) return;
        if (e.leaving) {
          e.leaving = false;
          this.route(e, "exit");
          return;
        }
        if (this.night) return;
        const r = Math.random();
        if (e.at === "desk" || e.at === "server" || e.at === "out") {
          if (r < 0.1) this.route(e, "coffee", this.randomSpot("coffee"));
          else if (r < 0.17) this.route(e, "meet", this.randomSpot("meet"));
          else if (r < 0.19) this.route(e, "server", this.randomSpot("server"));
          else if (r < 0.3) {
            const o = this.emps[Math.floor(Math.random() * this.emps.length)];
            if (o !== e && !(this.avoid && this.avoid(e.id, o.id))) {
              this.route(e, "desk", { x: o.seat.x + 1, y: o.seat.y });
              e.next = "desk";
            } else e.wait = 1;
          } else e.wait = 1 + Math.random() * 4;
        } else if (r < 0.55) this.seatRoute(e);
        else if (r < 0.75) this.route(e, e.at === "coffee" ? "meet" : "coffee", this.randomSpot(e.at === "coffee" ? "meet" : "coffee"));
        else e.wait = 1 + Math.random() * 3;
      });
    }
    float(id, text, color) {
      const e = this.byId[id];
      if (e) this.floaters.push({ x: e.x * TW + 8, y: e.y * TW - 6, text, color, life: 1.6 });
    }
    floatAt(x, y, text, color) { this.floaters.push({ x, y, text, color, life: 1.8 }); }
    burst(x, y, color, n) {
      for (let i = 0; i < (n || 14); i++) {
        const a = Math.random() * 6.28, s = 25 + Math.random() * 45;
        this.parts.push({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s - 25, life: 0.6 + Math.random() * 0.6, color });
      }
    }
    pulse(id, color) {
      const e = this.byId[id];
      if (e) this.burst(e.x * TW + 8, e.y * TW, color, 10);
    }
    draw() {
      const g = this.ctx;
      g.save();
      if (this.shake > 0) g.translate((Math.random() - 0.5) * this.shake, (Math.random() - 0.5) * this.shake);
      g.drawImage(this.stat, 0, 0);
      const vis = this.emps.filter((e) => e.vis).sort((a, b) => a.y - b.y);
      vis.forEach((e) => {
        const px = Math.round(e.x * TW), py = Math.round(e.y * TW);
        const dim = this.dim.has(e.id);
        g.globalAlpha = dim ? 0.38 : 1;
        g.fillStyle = "rgba(0,0,0,0.3)";
        g.fillRect(px + 3, py + 14, 10, 2);
        g.fillStyle = e.col;
        g.fillRect(px + 4, py + 15, 8, 1);
        const bob = e.moving ? (Math.floor((this.time + e.ph) * 8) % 2) : (Math.floor((this.time + e.ph) * 1.4) % 2 ? 0 : 0);
        const stretch = e.moving ? 0 : Math.floor((this.time * 1.5 + e.ph) % 2) ? 0 : 0;
        g.save();
        if (e.dir < 0) { g.translate(px + 16, py - bob - stretch); g.scale(-1, 1); g.drawImage(e.spr, 0, 0); }
        else g.drawImage(e.spr, px, py - bob - stretch);
        g.restore();
        g.globalAlpha = 1;
        const ring = this.rings[e.id];
        if (ring) {
          g.strokeStyle = ring;
          g.lineWidth = 1;
          g.strokeRect(px + 1.5, py - 0.5, 13, 16);
        }
        if (this.selected === e.id) {
          const a = 1.5 + Math.sin(this.time * 6);
          g.strokeStyle = "#fff";
          g.strokeRect(px - a + 1, py - a, 14 + a * 2, 17 + a);
        }
        const b = this.badges[e.id];
        if (b) {
          g.font = "bold 8px monospace";
          const w = g.measureText(b.text).width + 4;
          g.fillStyle = b.color;
          g.fillRect(px + 8 - w / 2, py - 11, w, 9);
          g.fillStyle = "#101520";
          g.fillText(b.text, px + 10 - w / 2, py - 4);
        }
      });
      if (this.dark > 0.01) {
        g.fillStyle = "rgba(8,12,44," + this.dark + ")";
        g.fillRect(0, 0, GW * TW, GH * TW);
        for (let i = 0; i < 40; i++) {
          const cx = 3 + 3 * (i % 8), cy = 4 + 4 * Math.floor(i / 8);
          g.fillStyle = "rgba(255,230,150," + this.dark * 0.18 + ")";
          g.fillRect(cx * TW, (cy - 1) * TW, 32, 16);
        }
      }
      const lab = (this.hover && this.byId[this.hover]) || (this.selected && this.byId[this.selected]);
      if (lab && lab.vis) {
        g.font = "bold 8px monospace";
        const t = lab.id + " " + lab.name, w = g.measureText(t).width + 6;
        const x = Math.min(GW * TW - w - 2, Math.max(2, lab.x * TW + 8 - w / 2)), y = lab.y * TW - 24;
        g.fillStyle = "#0e1220";
        g.fillRect(x, y, w, 10);
        g.fillStyle = lab.col;
        g.fillRect(x, y, 2, 10);
        g.fillStyle = "#fff";
        g.fillText(t, x + 4, y + 8);
      }
      this.parts.forEach((p) => {
        g.globalAlpha = Math.min(1, p.life * 2);
        g.fillStyle = p.color;
        g.fillRect(Math.round(p.x), Math.round(p.y), 2, 2);
      });
      g.globalAlpha = 1;
      g.font = "bold 8px monospace";
      this.floaters.forEach((f) => {
        g.globalAlpha = Math.min(1, f.life * 1.5);
        g.fillStyle = "#000";
        g.fillText(f.text, f.x - g.measureText(f.text).width / 2 + 1, f.y + 1);
        g.fillStyle = f.color;
        g.fillText(f.text, f.x - g.measureText(f.text).width / 2, f.y);
      });
      g.globalAlpha = 1;
      g.restore();
    }
    pos(e) {
      const r = this.cv.getBoundingClientRect();
      return [((e.clientX - r.left) / r.width) * GW * TW, ((e.clientY - r.top) / r.height) * GH * TW];
    }
    hit(e) {
      const [x, y] = this.pos(e);
      let best = null, bd = 11;
      this.emps.forEach((m) => {
        if (!m.vis) return;
        const d = Math.hypot(m.x * TW + 8 - x, m.y * TW + 8 - y);
        if (d < bd) { bd = d; best = m.id; }
      });
      return best;
    }
    click(e) {
      const id = this.hit(e);
      if (id && this.onSelect) this.onSelect(id);
    }
  }
  window.Office = Office;
  window.loadImg = load;
  window.DEPT_COL = DEPT_COL;
})();
