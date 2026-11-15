(function () {
  const CSS = ".fd-list{display:flex;flex-direction:column;gap:8px;max-height:52vh;overflow:auto}.fd-row{display:flex;align-items:center;gap:10px;min-height:56px;padding:6px 10px;background:#1b2434;border:3px solid #10151f;color:#fff;font:700 15px ui-monospace,Menlo,Consolas,monospace;text-align:left;width:100%}button.fd-row{cursor:pointer}.fd-row img{width:40px;height:40px;image-rendering:pixelated;flex:none;background:#2a3650}.fd-row .t{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fd-row .d{opacity:.7;font-size:12px}.fd-h{display:flex;align-items:center;gap:8px;font:800 18px ui-monospace,Menlo,Consolas,monospace;color:#fff;margin-bottom:10px}.fd-big{display:flex;flex-direction:column;align-items:center;gap:10px;padding:14px;color:#fff;font:800 20px ui-monospace,Menlo,Consolas,monospace;text-align:center}.fd-card{padding:12px;background:#fff;color:#10151f;border:3px solid #10151f;font:700 16px/1.35 ui-monospace,Menlo,Consolas,monospace}.fd-ch{display:flex;flex-wrap:wrap;gap:8px}.fd-ch button{min-height:56px;padding:0 14px;background:#2a3650;color:#fff;border:3px solid #10151f;font:800 14px ui-monospace,Menlo,Consolas,monospace;cursor:pointer}.fd-new{position:absolute;pointer-events:none}";
  let W, cache, lit, t0;

  function esc(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }
  function face(id) {
    const e = W.empAt(id);
    return e && e.spr ? '<img alt="" src="' + e.spr.toDataURL() + '">' : "";
  }
  function first(id) {
    const e = W.empAt(id);
    return e ? e.name.split(" ")[0] : id;
  }
  function short(t, n) {
    return t.length > n ? t.slice(0, n - 1) + "…" : t;
  }
  function head(ic, txt) {
    return '<div class="fd-h">' + W.icon(ic, 28) + "<span>" + esc(txt) + "</span></div>";
  }
  function costBtn(label, ic, run) {
    return [{ label, icon: ic, primary: true, onClick: run, keep: true }];
  }
  function guard() {
    if (W.env.over) return false;
    if (W.env.actions <= 0) { W.toast("NO ACTIONS LEFT", "bad"); return false; }
    return true;
  }
  function key(k) {
    return k + ":" + W.env.day;
  }

  function inboxList(msgs, close) {
    const rows = msgs.slice(-5).reverse().map((m, i) => '<button class="fd-row" data-i="' + i + '">' + face(m.sender) + '<span class="t">' + esc(first(m.sender)) + " · " + esc(short(m.subject, 26)) + '</span><span class="d">D' + m.day + "</span></button>").join("");
    close.setHtml(head("mail", "INBOX") + '<div class="fd-list">' + (rows || '<div class="fd-big">' + W.icon("mail", 40) + "EMPTY</div>") + "</div>");
    const view = msgs.slice(-5).reverse();
    close.body.querySelectorAll("button.fd-row").forEach((b) => b.addEventListener("click", () => {
      const m = view[+b.dataset.i];
      close.setHtml(head("mail", first(m.sender)) + '<div class="fd-row">' + face(m.sender) + '<span class="t">' + esc(short(m.subject, 30)) + '</span></div><div class="fd-card" style="margin-top:8px">' + esc(m.snippet) + "</div>");
      close.setButtons([{ label: "BACK", icon: "back", onClick: () => { inboxList(msgs, close); close.setButtons(deskButtons(close)); return false; }, keep: true }]);
    }));
  }
  function runSearch(q, close) {
    const k = key("s:" + q);
    let r = cache[k];
    if (!r) {
      if (!guard()) return;
      r = W.act("search_messages", { query: q });
      if (!r.ok) { W.toast("NOTHING", "bad"); return; }
      cache[k] = r;
    }
    inboxList(r.data.messages, close);
    close.setButtons(deskButtons(close));
  }
  function searchView(close) {
    const docs = (W.env.call("list_documents", { day_from: Math.max(1, W.env.day - 2) }).data.documents || []).filter((d) => !d.is_canary);
    const seen = {}, chips = [];
    docs.slice(-4).forEach((d) => { if (!seen[d.title]) { seen[d.title] = 1; chips.push(d.title); } });
    chips.push("frustrated");
    close.setHtml(head("search", "SEARCH") + '<div class="fd-ch">' + chips.map((c, i) => '<button data-i="' + i + '">' + esc(short(c, 22).toUpperCase()) + "</button>").join("") + "</div>");
    close.body.querySelectorAll(".fd-ch button").forEach((b) => b.addEventListener("click", () => runSearch(chips[+b.dataset.i].toLowerCase() === "frustrated" ? "frustrated" : chips[+b.dataset.i], close)));
    close.setButtons([{ label: "BACK", icon: "back", onClick: () => { deskHome(close); return false; }, keep: true }]);
  }
  function deskButtons(close) {
    return [
      { label: "INBOX", icon: "mail", primary: true, keep: true, onClick: () => { openInbox(close); return false; } },
      { label: "SEARCH", icon: "search", keep: true, onClick: () => { searchView(close); return false; } },
      { label: "", icon: "x" }
    ];
  }
  function openInbox(close) {
    const k = key("inbox");
    let r = cache[k];
    if (!r) {
      if (!guard()) return;
      r = W.act("search_messages", { query: "e" });
      if (!r.ok) { W.toast("NOTHING", "bad"); return; }
      cache[k] = r;
    }
    inboxList(r.data.messages, close);
    close.setButtons(deskButtons(close));
  }
  function deskHome(close) {
    close.setHtml('<div class="fd-big">' + W.icon("monitor", 56) + "YOUR PC</div>");
    close.setButtons(deskButtons(close));
  }
  function useDesk() {
    const close = W.openModal("", []);
    deskHome(close);
  }

  function logRows(logs) {
    return logs.slice(0, 14).map((l) => '<div class="fd-row">' + face(l.employee) + '<span class="t">' + esc(first(l.employee)) + '</span>' + W.icon("paper", 22) + '<span class="t">' + esc(l.doc_id) + "</span>" + (l.after_hours ? W.icon("moon", 24) : "") + '<span class="d">D' + l.day + "</span></div>").join("");
  }
  function showLogs(close, r) {
    const logs = r.data.logs;
    close.setHtml(head("log", "ACCESS LOGS") + '<div class="fd-list">' + (logRows(logs) || '<div class="fd-big">' + W.icon("log", 40) + "NONE</div>") + "</div>");
    close.setButtons([{ label: "", icon: "x" }]);
  }
  function useServer() {
    const d = W.env.day;
    if (d < 2) { W.openModal('<div class="fd-big">' + W.icon("log", 56) + "NO LOGS YET</div>", [{ label: "", icon: "x", primary: true }]); return; }
    const k = key("logs");
    const close = W.openModal('<div class="fd-big">' + W.icon("rack", 56) + "ACCESS LOGS</div>", []);
    if (cache[k]) { showLogs(close, cache[k]); return; }
    close.setButtons(costBtn("READ", "log", () => {
      if (!guard()) return false;
      const r = W.act("read_access_logs", { day_from: Math.max(1, d - 2), day_to: d - 1 });
      if (!r.ok) { W.toast("NOTHING", "bad"); return false; }
      cache[k] = r;
      showLogs(close, r);
      return false;
    }));
  }

  function surfaced() {
    return W.env.feed().filter((f) => f.surfaced_day === W.env.day);
  }
  function leakView(items) {
    return items.map((f) => '<div class="fd-row" style="min-height:72px">' + (f.variant ? W.shapeSvg(f.variant, 56) : W.icon("paper", 48)) + '<span class="t">' + esc(short(f.title, 24)) + '</span><span class="d">D' + f.surfaced_day + "</span></div>").join("");
  }
  function useTv() {
    lit = false;
    const all = W.env.feed();
    const last = all[all.length - 1];
    let html;
    if (!last) html = '<div class="fd-big">' + W.icon("tv", 56) + "NO LEAKS</div>";
    else {
      html = head("tv", "LEAK") + '<div class="fd-big" style="background:#3a1620;border:3px solid #10151f">' + (last.variant ? W.shapeSvg(last.variant, 120) + "<span>VERSION " + esc(last.variant) + "</span>" : W.icon("paper", 96)) + "<span>" + esc(short(last.title, 28)) + "</span></div>";
      const rest = all.slice(0, -1).reverse().slice(0, 4);
      if (rest.length) html += '<div class="fd-list" style="margin-top:8px">' + leakView(rest) + "</div>";
    }
    W.openModal(html, [{ label: "", icon: "x", primary: true }]);
  }
  function check() {
    if (!W.env || W.env.over) return;
    const s = surfaced();
    if (s.length) {
      lit = true;
      W.toast("LEAK ON TV");
    }
  }
  function drawTv(g, w) {
    if (!lit) return;
    const p = 0.5 + 0.5 * Math.sin((performance.now() - t0) / 180);
    g.fillStyle = "rgba(255,70,70," + (0.35 + 0.35 * p) + ")";
    g.fillRect(21 * 16, 1 * 16, 48, 16);
    g.fillStyle = "#fff";
    g.fillRect(22 * 16 + 4, 1 * 16 + 3, 8, 10);
    g.fillStyle = "#10151f";
    g.fillRect(22 * 16 + 6, 1 * 16 + 5, 4, 1);
    g.fillRect(22 * 16 + 6, 1 * 16 + 8, 4, 1);
  }

  window.Feat_desk = {
    init(world) {
      W = world;
      cache = {};
      lit = false;
      t0 = performance.now();
      if (!document.getElementById("fd-css")) {
        const s = document.createElement("style");
        s.id = "fd-css";
        s.textContent = CSS;
        document.head.appendChild(s);
      }
      W.onEvent("use:desk_pc", useDesk);
      W.onEvent("use:server_term", useServer);
      W.onEvent("use:feed_tv", useTv);
      W.onEvent("day:start", check);
      W.onEvent("mode:enter", () => { cache = {}; lit = false; });
      W.onDraw(drawTv, "over");
    }
  };
})();
