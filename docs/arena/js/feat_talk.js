(function () {
  const T = [
    ["recent_documents", "docs", "WHAT DID YOU OPEN?"],
    ["contacts_outside", "mail", "WHO OUTSIDE?"],
    ["workload", "clock", "HOW BUSY?"],
    ["access_needs", "key", "WHO HAS ACCESS?"]
  ];
  const cut = (s, n) => {
    const w = String(s).split(/\s+/);
    return w.length > n ? w.slice(0, n).join(" ") + "..." : w.join(" ");
  };
  window.Feat_talk = {
    init(W) {
      let close = null, rm = null, cur = null;
      const say = (e, t, ms) => {
        if (rm) rm();
        rm = W.bubble(e.x, e.y - 0.6, t, ms || 4200);
      };
      const head = (e) => '<div style="display:flex;align-items:center;gap:10px;font-weight:700">' + W.icon("people", 28) + "<span>" + e.name + '</span><span style="opacity:.6;font-size:.8em">' + e.dept + "</span></div>";
      const buttons = (e) =>
        T.map((t) => ({
          label: t[2],
          icon: t[1],
          primary: t[0] === "recent_documents",
          keep: true,
          onClick() {
            const r = W.act("interview", { employee: e.id, topic: t[0] });
            if (!r.ok) {
              W.toast("NO TIME LEFT", "bad");
              return false;
            }
            const a = cut(r.data.answer, 10);
            say(e, a);
            close.setHtml(head(e) + '<div style="margin-top:12px;font-size:1.1em">"' + a + '"</div>');
            return false;
          }
        })).concat([{ label: "BYE", icon: "x", onClick() {} }]);
      W.onEvent("talk", (p) => {
        const e = W.empAt(p.id);
        if (!e || W.busy || W.modalOpen()) return;
        cur = e;
        close = W.openModal(head(e) + '<div style="margin-top:12px;opacity:.7">Ask something. Costs time.</div>', buttons(e));
        say(e, "Yes?", 1800);
      });
    }
  };
})();
