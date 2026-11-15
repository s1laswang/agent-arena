(function () {
  const COL = { A: "#ff7a59", B: "#4cc9f0", C: "#9be564" };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  let W, batch, last, revealed;

  function css() {
    if (document.getElementById("fc-css")) return;
    const s = document.createElement("style");
    s.id = "fc-css";
    s.textContent = ".fc-h{font-weight:800;font-size:20px;text-align:center;margin:0 0 10px;color:var(--yl)}" +
      ".fc-g{display:grid;grid-template-columns:repeat(auto-fill,minmax(76px,1fr));gap:8px;max-height:52vh;overflow:auto;padding:2px}" +
      ".fc-p{min-height:88px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:4px;font:800 12px ui-monospace,Menlo,monospace;color:var(--tx);background:var(--pn2);border:3px solid var(--ln);cursor:pointer}" +
      ".fc-p img{width:48px;height:48px;image-rendering:pixelated}.fc-p.on{background:var(--yl);color:#1a1400}" +
      ".fc-r{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin:10px 0}.fc-c{min-width:92px;padding:8px;text-align:center;background:var(--pn2);border:3px solid var(--ln)}" +
      ".fc-c b{display:block;font-size:26px}.fc-n{text-align:center;font-weight:800;margin:6px 0}";
    document.head.appendChild(s);
  }

  const face = (e, n) => '<img src="' + e.spr.toDataURL() + '" width="' + (n || 48) + '" height="' + (n || 48) + '" alt="">';
  const first = (e) => e.name.split(" ")[0];

  function docs() {
    const d = W.env.day, all = W.env.docs.filter((x) => !x.is_canary);
    const t = all.filter((x) => x.day === d);
    return (t.length ? t : all.filter((x) => x.day >= d - 2)).slice(-4);
  }

  function printer() {
    if (W.env.over) return;
    if (!batch) return pickDoc();
    const n = Object.keys(batch.assign).length;
    const b = batch.labels.map((l) => ({ label: l, icon: "paper", onClick: () => { W.setCarry({ type: "trap", data: { label: l } }); last = W.player.carrying; } }));
    b.push({ label: "SEND " + n, icon: "send", primary: true, onClick: () => { flush(); } });
    b.push({ icon: "x", onClick: () => { batch = null; W.setCarry(null); } });
    W.openModal('<div class="fc-h">TRAP ' + esc(batch.title.slice(0, 30)) + '</div><div class="fc-n">Take a copy. Drop on a desk.</div>', b);
  }

  function pickDoc() {
    if (W.env.actions < 1) return W.toast("No actions left", "bad");
    const ds = docs();
    if (!ds.length) return W.toast("Nothing to copy");
    const b = ds.map((d) => ({ label: esc(d.title.slice(0, 26)), icon: "docs", onClick: () => pickN(d) }));
    b.push({ icon: "x" });
    W.openModal('<div class="fc-h">PRINT TRAP</div><div class="fc-n">Which paper?</div>', b);
  }

  function pickN(d) {
    const mk = (n) => ({ label: n + " VERSIONS", icon: "paper", primary: n === 3, onClick: () => { batch = { title: d.title, labels: ["A", "B", "C"].slice(0, n), assign: {} }; W.toast("Printed. Take a copy."); } });
    setTimeout(() => W.openModal('<div class="fc-h">HOW MANY?</div><div class="fc-n">Costs 1 action</div>', [mk(2), mk(3), { icon: "x" }]), 0);
    return false;
  }

  function deliver(id) {
    const c = W.player.carrying, e = W.empAt(id);
    if (!c || !batch || !e) return false;
    if (W.env.restricted.has(id)) { W.toast("Restricted", "bad"); return true; }
    const l = c.data.label;
    batch.assign[id] = l;
    W.setCarry(null);
    last = null;
    W.bubble(e.x + 0.5, e.y, "Got it " + l, 1600);
    return true;
  }

  function flush() {
    if (!batch) return;
    const b = batch;
    batch = null;
    W.setCarry(null);
    last = null;
    if (!Object.keys(b.assign).length) return W.toast("Unsent. Wasted.", "bad");
    const r = W.act("plant_canary", { doc_title: b.title, assignment: b.assign });
    W.toast(r.ok ? "Trap planted" : "Failed: " + r.error, r.ok ? "good" : "bad");
  }

  function endDay() {
    if (W.busy || W.env.over) return;
    const note = batch ? '<div class="fc-n">Unsent copies are sent now.</div>' : "";
    W.openModal('<div class="fc-h">END DAY?</div>' + note, [
      { label: "END DAY", icon: "moon", primary: true, onClick: () => { const r = W.act("advance_day"); if (r.ok && r.data.episode_over) setTimeout(reveal, 700); } },
      { icon: "x" }
    ]);
  }

  function accuse() {
    if (W.env.over) return reveal();
    let sel = null;
    const cell = (e) => '<button class="fc-p" data-id="' + e.id + '" style="border-color:' + e.col + '">' + face(e) + "<span>" + esc(first(e)) + "</span></button>";
    const html = '<div class="fc-h">WHO IS THE MOLE?</div><div class="fc-n">Wrong = -1. One try.</div><div class="fc-g">' + W.employees.map(cell).join("") + "</div>";
    const bs = () => [
      { label: sel ? "ACCUSE " + esc(first(W.empAt(sel))) : "PICK ONE", icon: "check", primary: !!sel, onClick: () => { if (!sel) return false; confirm(sel); } },
      { icon: "x" }
    ];
    const close = W.openModal(html, bs());
    close.body.querySelectorAll(".fc-p").forEach((b) => b.addEventListener("click", () => {
      sel = b.dataset.id;
      close.body.querySelectorAll(".fc-p").forEach((x) => x.classList.toggle("on", x === b));
      close.setButtons(bs());
    }));
  }

  function confirm(id) {
    const e = W.empAt(id);
    setTimeout(() => W.openModal('<div class="fc-h">SURE?</div><div class="fc-r">' + face(e, 96) + '</div><div class="fc-n">' + esc(e.name) + "<br>" + esc(e.dept) + "</div>", [
      { label: "YES", icon: "check", primary: true, onClick: () => { flush(); W.act("accuse", { employee: id }); setTimeout(reveal, 400); } },
      { label: "BACK", icon: "back", onClick: () => { setTimeout(accuse, 0); return false; } }
    ]), 0);
    return false;
  }

  function reveal() {
    const env = W.env;
    if (!env.over || W.modalOpen()) return;
    revealed = true;
    const mole = W.empAt(env.w.mole), row = window.AD.index.seeds.find((x) => x.seed === env.seed);
    const won = env.accused === env.w.mole, you = env.score;
    const best = Math.max(you, row ? row.gemini.score : -9, row ? row.solver.score : -9);
    const card = (n, s, ok) => '<div class="fc-c" style="border-color:' + (s === best ? "var(--yl)" : "var(--ln)") + '"><span>' + n + "</span><b>" + s.toFixed(2) + "</b><span>" + (ok == null ? "" : ok ? "caught" : "missed") + "</span></div>";
    const head = env.accused ? (won ? "CAUGHT HIM" : "WRONG ONE") : "NO ACCUSATION";
    const html = '<div class="fc-h">' + head + '</div><div class="fc-r">' + face(mole, 96) + '</div><div class="fc-n">Mole: ' + esc(mole.name) + "<br>" + esc(mole.dept) + "</div>" +
      '<div class="fc-r">' + card("YOU", you, env.accused ? won : null) + (row ? card("GEMINI", row.gemini.score, row.gemini.correct) + card("SOLVER", row.solver.score, row.solver.correct) : "") + "</div>";
    W.openModal(html, [
      { label: "AGAIN", icon: "repeat", primary: true, onClick: () => { W.stop(); window.startWalk(env.seed); } },
      { label: "MENU", icon: "back", onClick: () => W.stop() },
      { label: "LOOK", icon: "eye" }
    ]);
  }

  window.Feat_carry = {
    init(w) {
      W = w;
      batch = null;
      last = null;
      revealed = false;
      css();
      W._carryFlush = flush;
      if (!W._carryWrap) {
        const a = W.act;
        W.act = (t, g) => { if (t === "advance_day" && W._carryFlush) W._carryFlush(); return a(t, g); };
        W._carryWrap = 1;
      }
      W.registerInteractable(Object.assign({}, W.getInteractable("printer"), { onUse: printer }));
      W.employees.forEach((e) => {
        const o = W.getInteractable("emp:" + e.id), u = o.onUse;
        W.registerInteractable(Object.assign({}, o, { onUse: (c) => { if (!deliver(e.id)) u(c); } }));
      });
      W.onEvent("use:printer", printer);
      W.onEvent("use:bell", endDay);
      W.onEvent("bell", endDay);
      W.onEvent("use:red_door", accuse);
      W.onEvent("carry:drop", () => {
        if (!last) return;
        const p = W.player, near = W.employees.filter((e) => Math.hypot(e.x + 0.5 - p.x, e.y + 0.5 - p.y) < 1.6).sort((a, b) => Math.hypot(a.x - p.x, a.y - p.y) - Math.hypot(b.x - p.x, b.y - p.y))[0];
        W.setCarry(last);
        if (!near || !deliver(near.id)) { W.setCarry(null); W.toast("Back in tray"); }
        last = null;
      });
      W.onFrame(() => { if (W.player.carrying) last = W.player.carrying; });
      W.onDraw((ctx) => {
        ctx.save();
        ctx.font = "bold 7px monospace";
        ctx.textAlign = "center";
        if (batch) Object.keys(batch.assign).forEach((id) => {
          const e = W.empAt(id), l = batch.assign[id], x = e.x * 16 + 12, y = e.y * 16 + 1;
          ctx.fillStyle = COL[l];
          ctx.fillRect(x - 4, y - 4, 8, 8);
          ctx.fillStyle = "#10151f";
          ctx.fillText(l, x, y + 2.5);
        });
        if (revealed) {
          const m = W.empAt(W.env.w.mole);
          ctx.strokeStyle = "#ff5a5a";
          ctx.lineWidth = 2;
          ctx.strokeRect(m.x * 16 - 1, m.y * 16 - 1, 18, 18);
        }
        ctx.restore();
      }, "over");
    }
  };
})();
