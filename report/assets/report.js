/* Poisoned Inbox report: theme toggle, tooltips and the replay viewer.
   Inlined into report.html by build_report.py. Plain JS, no libraries, no network.
   All data text is inserted with textContent (never innerHTML). */
(function () {
  "use strict";

  var DATA = {};
  try {
    var dataEl = document.getElementById("report-data");
    DATA = JSON.parse((dataEl && dataEl.textContent) || "{}") || {};
  } catch (e) {
    DATA = {};
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function chip(cls, text) { return el("span", "chip " + (cls || ""), text); }

  /* ---------------------------------------------------------------- theme */
  var root = document.documentElement;
  var themeBtn = document.getElementById("theme-btn");
  function currentTheme() { return root.getAttribute("data-theme") || "auto"; }
  function setTheme(t, save) {
    if (t === "light" || t === "dark") root.setAttribute("data-theme", t);
    else root.removeAttribute("data-theme");
    if (themeBtn) themeBtn.textContent = "Theme: " + (t === "light" || t === "dark" ? t : "auto");
    if (save) {
      try { localStorage.setItem("pinbox-report-theme", t); } catch (e) { /* storage blocked: fine */ }
    }
  }
  if (themeBtn) {
    setTheme(currentTheme(), false);
    themeBtn.addEventListener("click", function () {
      var order = ["auto", "light", "dark"];
      setTheme(order[(order.indexOf(currentTheme()) + 1) % order.length], true);
    });
  }

  /* ---------------------------------------------------------------- tooltip */
  var tip = document.getElementById("tip");
  var tipTarget = null;
  function placeTip(x, y) {
    if (!tip) return;
    var r = tip.getBoundingClientRect();
    var left = x + 14, top = y + 16;
    if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > window.innerHeight - 8) top = y - r.height - 14;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }
  function showTip(target, x, y) {
    var text = target.getAttribute("data-tip");
    if (!tip || !text) return;
    tip.textContent = "";
    text.split("\n").forEach(function (line, i) { tip.appendChild(el("div", i === 0 ? "tip-h" : "", line)); });
    tip.hidden = false;
    placeTip(x, y);
  }
  function hideTip() {
    if (tip) tip.hidden = true;
    tipTarget = null;
  }
  document.addEventListener("pointermove", function (ev) {
    var t = ev.target && ev.target.closest ? ev.target.closest("[data-tip]") : null;
    if (!t) { if (tipTarget) hideTip(); return; }
    if (t !== tipTarget) { tipTarget = t; showTip(t, ev.clientX, ev.clientY); }
    else placeTip(ev.clientX, ev.clientY);
  });
  document.addEventListener("pointerleave", hideTip);
  document.addEventListener("focusin", function (ev) {
    var t = ev.target && ev.target.closest ? ev.target.closest("[data-tip]") : null;
    if (t) { var r = t.getBoundingClientRect(); tipTarget = t; showTip(t, r.left + r.width / 2, r.bottom); }
  });
  document.addEventListener("focusout", hideTip);
  window.addEventListener("scroll", hideTip, { passive: true });

  /* ---------------------------------------------------------------- replay */
  var RP = DATA.replay || {};
  var RUNS = Array.isArray(RP.runs) ? RP.runs : [];
  var replayRoot = document.getElementById("replay-root");
  var TAG_HELP = DATA.tag_help || {};

  function initReplay() {
    var $ = function (id) { return document.getElementById(id); };
    var selAgent = $("rp-agent"), selEp = $("rp-episode");
    var list = $("rp-list"), strip = $("rp-strip"), detail = $("rp-detail"), summary = $("rp-summary");
    var bFirst = $("rp-first"), bPrev = $("rp-prev"), bNext = $("rp-next"), bPlay = $("rp-play");
    var bJump = $("rp-jump"), bCmp = $("rp-compare");
    var pos = el("span", "rp-pos");
    bCmp.parentNode.appendChild(pos);

    var GROUP_LABEL = { reference: "our script", llm: "AI agent", baseline: "baseline", ladder: "ladder" };
    var GROUP_RANK = { llm: 0, reference: 1, baseline: 2, ladder: 3 };
    var byKey = {}, byAgent = {}, agents = [], groupOf = {};
    RUNS.forEach(function (r) {
      byKey[r.key] = r;
      groupOf[r.agent] = r.group;
      if (!byAgent[r.agent]) { byAgent[r.agent] = []; agents.push(r.agent); }
      byAgent[r.agent].push(r);
    });
    function rank(agent) { var g = groupOf[agent]; return GROUP_RANK.hasOwnProperty(g) ? GROUP_RANK[g] : 9; }
    agents.sort(function (a, b) {
      var d = rank(a) - rank(b);
      return d || (a < b ? -1 : a > b ? 1 : 0);
    });
    Object.keys(byAgent).forEach(function (a) {
      byAgent[a].sort(function (x, y) {
        if (x.episode_id !== y.episode_id) return x.episode_id < y.episode_id ? -1 : 1;
        return Number(x.repeat) - Number(y.repeat);
      });
    });
    agents.forEach(function (a) {
      var o = el("option", "", a + " (" + (GROUP_LABEL[groupOf[a]] || groupOf[a]) + ")");
      o.value = a;
      selAgent.appendChild(o);
    });

    var run = null, cur = 0, timer = null, history = [];

    function level(s) {
      var lvl = "";
      (s.marks || []).forEach(function (m) { if (m.level === "break") lvl = "break"; else if (!lvl) lvl = "possible"; });
      return lvl;
    }
    function isBreak(s) { return level(s) === "break"; }
    function passed(r) { return r.reward !== null && r.reward !== undefined && r.reward >= 1; }
    function stepClass(s) {
      var c = "k-" + (s.kind || "read");
      if (s.ok === false) c += " is-err";
      var l = level(s);
      if (l) c += " m-" + l;
      return c;
    }
    function chipsFor(s) {
      var out = [];
      if (s.kind === "write") out.push(chip("c-write", "◆ changes state"));
      if (s.kind === "verify") out.push(chip("c-verify", "☎ check"));
      if (s.ok === false) out.push(chip("c-error", "! error"));
      (s.marks || []).forEach(function (m) {
        out.push(m.level === "break" ? chip("c-break", "✖ broke policy: " + m.tag)
                                     : chip("c-maybe", "? maybe: " + m.tag));
      });
      return out;
    }
    function stepLabel(s) {
      if (s.kind === "event") return s.text || "New item arrived";
      var t = "Step " + s.n + ": " + s.tool;
      if (s.ok === false) t += "\nerror: " + s.error;
      (s.marks || []).forEach(function (m) { t += "\n" + (m.level === "break" ? "broke policy: " : "maybe: ") + m.tag; });
      return t;
    }
    function ruleFor(tag) {
      var fs = run.failures || [];
      for (var i = 0; i < fs.length; i++) if (fs[i].tag === tag && fs[i].rule) return fs[i].rule;
      return "";
    }
    function nCalls(r) { return r.steps.filter(function (s) { return s.kind !== "event"; }).length; }

    function fillEpisodes(agent, selectKey) {
      selEp.textContent = "";
      (byAgent[agent] || []).forEach(function (r) {
        var nb = r.steps.filter(isBreak).length;
        var label = (passed(r) ? "✓ pass" : "✖ fail") + " · " + r.episode_id + " · run " + r.repeat;
        if (nb) label += " · " + nb + " policy break" + (nb > 1 ? "s" : "");
        var o = el("option", "", label);
        o.value = r.key;
        selEp.appendChild(o);
      });
      if (selectKey) selEp.value = selectKey;
    }

    function addFact(parent, k, v) {
      var f = el("div", "fact");
      f.appendChild(el("span", "k", k));
      f.appendChild(el("span", "v", v));
      parent.appendChild(f);
    }

    function renderSummary() {
      summary.textContent = "";
      var top = el("div", "rp-sum-top");
      top.appendChild(el("span", "badge " + (passed(run) ? "b-pass" : "b-fail"),
        passed(run) ? "✓ Reward 1" : "✖ Reward 0"));
      addFact(top, "Agent", run.agent);
      addFact(top, "Episode", run.episode_id);
      addFact(top, "Run", String(run.repeat));
      if (typeof run.progress === "number") addFact(top, "Checks passed", Math.round(run.progress * 100) + "%");
      addFact(top, "Tool calls", String(nCalls(run)));
      summary.appendChild(top);
      if (run.truncated) summary.appendChild(el("p", "small muted", "Long run: only the first calls are shown."));
      var fails = run.failures || [];
      if (fails.length) {
        var ul = el("ul", "rp-fails");
        fails.forEach(function (f) {
          var linked = f.steps && f.steps.length;
          var li = el("li", "rp-fail" + (linked ? "" : " is-omission"));
          var head = el("div", "rp-fail-head");
          head.appendChild(el("code", "tag", f.tag));
          head.appendChild(el("span", "rp-fail-help", f.help || TAG_HELP[f.tag] || "Unknown tag (shown as the grader wrote it)."));
          if (f.rule) head.appendChild(el("span", "rp-fail-rule", f.rule));
          li.appendChild(head);
          if (f.detail) li.appendChild(el("div", "rp-fail-detail", f.detail));
          var act = el("div", "rp-fail-act");
          if (linked) {
            f.steps.forEach(function (idx) {
              var s = run.steps[idx];
              if (!s) return;
              var b = el("button", "linkbtn", "Go to step " + s.n);
              b.type = "button";
              b.addEventListener("click", function () { stop(); go(idx, true); showBody(); });
              act.appendChild(b);
            });
          } else {
            act.appendChild(el("span", "small muted", f.omission ? "Something it never did" : "Not tied to one call"));
          }
          li.appendChild(act);
          ul.appendChild(li);
        });
        summary.appendChild(ul);
      } else if (passed(run)) {
        summary.appendChild(el("p", "rp-ok", "✓ Every check passed. Nothing broke policy."));
      }
    }

    function renderStrip() {
      strip.textContent = "";
      run.steps.forEach(function (s, idx) {
        var b = el("button", "sc " + stepClass(s));
        b.type = "button";
        b.tabIndex = -1;
        b.setAttribute("data-tip", stepLabel(s));
        b.setAttribute("aria-label", stepLabel(s).replace(/\n/g, ", "));
        b.addEventListener("click", function () { stop(); go(idx, true); });
        strip.appendChild(b);
      });
    }

    function renderList() {
      list.textContent = "";
      run.steps.forEach(function (s, idx) {
        var li = el("li", "step " + stepClass(s));
        if (s.kind === "event") {
          li.appendChild(el("span", "n", "⚡"));
          var m = el("div", "main");
          m.appendChild(el("div", "ev-text", s.text));
          li.appendChild(m);
        } else {
          li.appendChild(el("span", "n", String(s.n)));
          var main = el("div", "main");
          var head = el("div", "head");
          head.appendChild(el("span", "tool", s.tool));
          chipsFor(s).forEach(function (c) { head.appendChild(c); });
          main.appendChild(head);
          if (s.args_short) main.appendChild(el("div", "args", s.args_short));
          var res = s.ok === false ? "error: " + (s.error || "") : s.result_short;
          if (res) main.appendChild(el("div", "res", "→ " + res));
          li.appendChild(main);
        }
        li.addEventListener("click", function () { stop(); go(idx, false); });
        list.appendChild(li);
      });
    }

    function renderDetail() {
      detail.textContent = "";
      var s = run.steps[cur];
      if (!s) { detail.appendChild(el("p", "empty", "This run has no tool calls.")); return; }
      if (s.kind === "event") {
        detail.appendChild(el("h3", "d-title", "⚡ Something new arrived"));
        detail.appendChild(el("p", "", s.text));
        detail.appendChild(el("p", "small muted", run.family === "ap_run"
          ? "New items can arrive while the agent works. Policy rule 6: check the queue again before finishing."
          : "New items can arrive while the agent works."));
        return;
      }
      var h = el("h3", "d-title", "Step " + s.n + " · ");
      h.appendChild(el("code", "", s.tool));
      detail.appendChild(h);
      var cs = el("div", "d-chips");
      chipsFor(s).forEach(function (c) { cs.appendChild(c); });
      if (!cs.children.length) cs.appendChild(chip("", "reads only"));
      detail.appendChild(cs);
      (s.marks || []).forEach(function (m) {
        var box = el("div", "why" + (m.level === "break" ? "" : " why-maybe"));
        box.appendChild(el("div", "why-h", m.level === "break" ? "✖ Why this broke policy" : "? This call may explain a failed check"));
        var line = el("div", "why-tag");
        line.appendChild(el("code", "tag", m.tag));
        var help = TAG_HELP[m.tag];
        if (help) line.appendChild(document.createTextNode(" " + help));
        box.appendChild(line);
        var rule = ruleFor(m.tag);
        if (rule) box.appendChild(el("div", "why-detail", "Policy: " + rule));
        if (m.why) box.appendChild(el("div", "why-detail", m.why));
        detail.appendChild(box);
      });
      detail.appendChild(el("div", "d-label", "Arguments"));
      var args = "{}";
      try { args = JSON.stringify(s.args || {}, null, 2); } catch (e) { /* keep {} */ }
      detail.appendChild(el("pre", "", args));
      if (s.ok === false) {
        detail.appendChild(el("div", "d-label", "Error from the tool"));
        detail.appendChild(el("pre", "err", s.error || "error"));
      } else {
        detail.appendChild(el("div", "d-label", "Result"));
        detail.appendChild(el("pre", "", s.result_text || "(empty)"));
      }
    }

    function keepVisible(item, center) {
      var t = item.offsetTop, b = t + item.offsetHeight;
      if (center) { list.scrollTop = Math.max(0, t - list.clientHeight / 3); return; }
      if (t < list.scrollTop + 6) list.scrollTop = t - 6;
      else if (b > list.scrollTop + list.clientHeight - 6) list.scrollTop = b - list.clientHeight + 6;
    }

    function go(idx, center) {
      if (!run) return;
      var n = run.steps.length;
      cur = Math.max(0, Math.min(n - 1, idx));
      var items = list.children, cells = strip.children, i;
      for (i = 0; i < items.length; i++) {
        items[i].classList.toggle("is-current", i === cur);
        items[i].classList.toggle("is-future", i > cur);
      }
      for (i = 0; i < cells.length; i++) {
        cells[i].classList.toggle("is-current", i === cur);
        cells[i].classList.toggle("is-future", i > cur);
      }
      if (items[cur]) keepVisible(items[cur], center);
      renderDetail();
      bFirst.disabled = bPrev.disabled = cur <= 0;
      bNext.disabled = cur >= n - 1;
      bJump.disabled = !run.steps.some(isBreak);
      var calls = 0, total = 0;
      for (i = 0; i < n; i++) {
        if (run.steps[i].kind !== "event") { total++; if (i <= cur) calls++; }
      }
      pos.textContent = !n ? "No tool calls" : run.steps[cur].kind === "event"
        ? "New item, after step " + calls + " of " + total
        : "Step " + calls + " of " + total;
    }

    var body = replayRoot.querySelector(".rp-body"), bar = replayRoot.querySelector(".rp-bar");
    function showBody() {
      // bring the list + detail fully into view (below the sticky top bar and step bar)
      if (!body) return;
      var top = 8, topbar = document.querySelector(".topbar");
      if (topbar && getComputedStyle(topbar).position === "sticky") top += topbar.offsetHeight;
      if (bar && getComputedStyle(bar).position === "sticky") top += bar.offsetHeight;
      var r = body.getBoundingClientRect();
      if (r.top < top || r.bottom > window.innerHeight) {
        var smooth = !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
        window.scrollTo({ top: window.scrollY + r.top - top, behavior: smooth ? "smooth" : "auto" });
      }
    }

    function stop() {
      if (timer) { clearInterval(timer); timer = null; }
      bPlay.textContent = "▶ Play";
    }
    function play() {
      if (timer) { stop(); return; }
      if (cur >= run.steps.length - 1) go(0, true);
      bPlay.textContent = "⏸ Pause";
      timer = setInterval(function () {
        if (cur >= run.steps.length - 1) { stop(); return; }
        go(cur + 1, false);
        if (isBreak(run.steps[cur])) stop();
      }, 1100);
    }
    function jump() {
      var n = run.steps.length;
      for (var k = 1; k <= n; k++) {
        var i = (cur + k) % n;
        if (isBreak(run.steps[i])) { stop(); go(i, true); showBody(); return; }
      }
    }

    function referenceFor(r) {
      if (r.group === "reference") return null;
      for (var i = 0; i < RUNS.length; i++) {
        if (RUNS[i].group === "reference" && RUNS[i].episode_id === r.episode_id) return RUNS[i];
      }
      return null;
    }
    var KEY_ARGS = ["invoice_id", "order_id", "ticket_id", "vendor_id", "email_id", "doc_id"];
    function keyArg(s) {
      var a = (s && s.args) || {};
      for (var i = 0; i < KEY_ARGS.length; i++) if (a[KEY_ARGS[i]] !== undefined) return KEY_ARGS[i] + "=" + a[KEY_ARGS[i]];
      return "";
    }
    function matchingStep(from, steps) {
      // the same moment in another run: same tool + same key argument, then any state change on the
      // same key argument (e.g. our script flags the invoice the AI paid), then the same tool
      if (!from || from.kind === "event") return 0;
      var k = keyArg(from), i;
      for (i = 0; i < steps.length; i++) if (steps[i].tool === from.tool && k && keyArg(steps[i]) === k) return i;
      for (i = 0; i < steps.length; i++) if (k && steps[i].kind === "write" && keyArg(steps[i]) === k) return i;
      for (i = 0; i < steps.length; i++) if (steps[i].tool === from.tool) return i;
      return 0;
    }
    function updateCompare() {
      var ref = referenceFor(run);
      if (ref) {
        bCmp.hidden = false;
        bCmp.textContent = "Compare with our script";
        bCmp.onclick = function () {
          var target = matchingStep(run.steps[cur], ref.steps);
          load(ref.key, "compare");
          go(target, true);
        };
      } else if (history.length) {
        var back = history[history.length - 1];
        bCmp.hidden = false;
        bCmp.textContent = "↩ Back to " + byKey[back.key].agent;
        bCmp.onclick = function () { var h = history.pop(); load(h.key, "back"); go(h.cur, true); };
      } else {
        bCmp.hidden = true;
        bCmp.onclick = null;
      }
    }

    function load(key, mode) {
      var r = byKey[key];
      if (!r) return;
      stop();
      if (mode === "compare" && run) history.push({ key: run.key, cur: cur });
      else if (mode !== "back") history = [];
      run = r;
      selAgent.value = r.agent;
      fillEpisodes(r.agent, r.key);
      renderSummary();
      renderStrip();
      renderList();
      list.scrollTop = 0;
      go(0, false);
      updateCompare();
    }

    function bestRunFor(agent) {
      var rs = byAgent[agent] || [];
      for (var i = 0; i < rs.length; i++) if (rs[i].steps.some(isBreak)) return rs[i];
      return rs[0];
    }

    selAgent.addEventListener("change", function () { var r = bestRunFor(selAgent.value); if (r) load(r.key); });
    selEp.addEventListener("change", function () { load(selEp.value); });
    bFirst.addEventListener("click", function () { stop(); go(0, true); });
    bPrev.addEventListener("click", function () { stop(); go(cur - 1, false); });
    bNext.addEventListener("click", function () { stop(); go(cur + 1, false); });
    bPlay.addEventListener("click", play);
    bJump.addEventListener("click", jump);

    function replayInView() {
      var r = replayRoot.getBoundingClientRect();
      return r.top < window.innerHeight * 0.75 && r.bottom > window.innerHeight * 0.25;
    }
    document.addEventListener("keydown", function (ev) {
      var t = ev.target, tag = t && t.tagName;
      if (tag === "SELECT" || tag === "INPUT" || tag === "TEXTAREA" || ev.altKey || ev.ctrlKey || ev.metaKey) return;
      if (!run || !replayInView()) return;
      if (ev.key === "ArrowRight") { stop(); go(cur + 1, false); ev.preventDefault(); }
      else if (ev.key === "ArrowLeft") { stop(); go(cur - 1, false); ev.preventDefault(); }
      else if (ev.key === "Home") { stop(); go(0, true); ev.preventDefault(); }
      else if (ev.key === "End") { stop(); go(run.steps.length - 1, true); ev.preventDefault(); }
    });

    load(byKey[RP["default"]] ? RP["default"] : RUNS[0].key);
  }

  if (replayRoot && RUNS.length) {
    try { initReplay(); } catch (e) {
      var msg = document.createElement("p");
      msg.className = "empty";
      msg.textContent = "The replay viewer could not start: " + e.message;
      replayRoot.appendChild(msg);
    }
  }
  document.body.setAttribute("data-ready", "1");
})();
