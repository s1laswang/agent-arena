(function () {
  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hash() {
    let h = 2166136261;
    for (const a of arguments) {
      const s = String(a);
      for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
      h = Math.imul(h ^ 124, 16777619);
    }
    return h >>> 0;
  }
  function poisson(r, l) {
    const L = Math.exp(-l);
    let k = 0, p = 1;
    do { k++; p *= r(); } while (p > L);
    return k - 1;
  }
  function pick(r, a) { return a[Math.floor(r() * a.length)]; }
  function shuffle(r, a) {
    a = a.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(r() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }
  const r2 = (x) => Math.round(x * 100) / 100;
  const ok = (data) => ({ ok: true, data, error: null });
  const bad = (error) => ({ ok: false, data: {}, error });

  const TOPICS = ["recent_documents", "contacts_outside", "workload", "access_needs"];
  const EVASIVE = ["I would rather not get into that.", "Why are you asking me? Ask someone else.", "No comment right now."];
  const WORK = ["Busy but fine, nothing unusual.", "Deadline crunch, I stay late a few times a week.", "Manageable, thanks for asking."];
  const OUTSIDE = ["Just a recruiter on LinkedIn, I ignored it.", "A vendor and my old university friends, nothing about work.", "No outside contacts about work."];
  const NEEDS = ["I have what I need.", "A bit more access to the shared drive would be nice.", "All good on my side."];
  const ANGRY = ["This is unacceptable, nobody listens to us.", "I am done with these decisions.", "Management keeps ignoring the real problems."];

  class Env {
    constructor(world, seed) {
      this.w = world;
      this.seed = seed;
      this.emp = {};
      world.employees.forEach((e) => (this.emp[e.id] = e));
      this.day = 1;
      this.Vtrue = 1;
      this.actions = 8;
      this.calls = 0;
      this.restricted = new Set();
      this.canaries = [];
      this.plantedToday = 0;
      this.docs = [];
      this.leaks = [];
      this.over = false;
      this.score = null;
      this.accused = null;
      this.costs = 0;
      this.logCache = {};
      this.msgCache = {};
      this.ivCache = {};
      this.events = [];
      this.addDay(1);
    }
    addDay(d) {
      this.w.docs.filter((x) => x.day === d).forEach((x) => {
        this.docs.push({
          doc_id: x.doc_id, title: x.title, day: d,
          recipients: x.recipients.filter((id) => !this.restricted.has(id)),
          is_canary: false
        });
      });
    }
    get V() {
      let v = this.Vtrue;
      this.leaks.forEach((l) => { if (l.surface > this.day) v += 0.05; });
      return Math.max(0, r2(v));
    }
    held(id, fromDay) {
      return this.docs.filter((d) => d.day >= (fromDay || 0) && d.recipients.includes(id));
    }
    spend(n) {
      if (this.actions <= 0) return false;
      this.actions -= n || 1;
      return true;
    }
    call(tool, a) {
      a = a || {};
      if (this.over) return bad("episode over");
      this.calls++;
      const f = this["t_" + tool];
      if (!f) return bad("unknown tool");
      return f.call(this, a);
    }
    t_status() {
      return ok({
        day: this.day, V: this.V, actions_left_today: this.actions, tool_calls_left: 420 - this.calls,
        restricted: [...this.restricted], canaries_planted: this.canaries.map((c) => c.id)
      });
    }
    t_list_employees() { return ok({ employees: this.w.employees }); }
    t_list_documents(a) {
      const f = a.day_from || 1, t = a.day_to || this.day;
      return ok({ documents: this.docs.filter((d) => d.day >= f && d.day <= t) });
    }
    t_read_access_logs(a) {
      if (!this.spend()) return bad("no actions left today");
      const f = Math.max(1, a.day_from || 1), t = Math.min(a.day_to || this.day - 1, this.day - 1);
      let out = [];
      for (let d = f; d <= t; d++) out = out.concat(this.logFor(d));
      if (a.employee) out = out.filter((l) => l.employee === a.employee);
      return ok({ logs: out });
    }
    logFor(d) {
      if (this.logCache[d]) return this.logCache[d];
      const r = rng(hash(this.seed, "log", d)), out = [];
      const ids = this.w.employees.map((e) => e.id);
      ids.forEach((id) => {
        const held = this.held(id).filter((x) => x.day <= d);
        if (!held.length) return;
        const n = poisson(r, 1);
        for (let i = 0; i < n; i++) {
          out.push({ day: d, employee: id, doc_id: pick(r, held).doc_id, after_hours: r() < (id === this.w.mole ? 0.3 : 0.1) });
        }
      });
      const todays = this.docs.filter((x) => x.day <= d);
      const fakes = poisson(r, 2);
      const others = ids.filter((i) => i !== this.w.mole && i !== this.w.decoy);
      for (let i = 0; i < fakes && todays.length; i++) {
        out.push({ day: d, employee: r() < 0.5 ? this.w.decoy : pick(r, others), doc_id: pick(r, todays).doc_id, after_hours: true });
      }
      out.sort((a, b) => (a.employee < b.employee ? -1 : a.employee > b.employee ? 1 : 0));
      return (this.logCache[d] = out);
    }
    msgsFor(d) {
      if (this.msgCache[d]) return this.msgCache[d];
      const r = rng(hash(this.seed, "msg", d)), out = [];
      let n = 0;
      this.docs.filter((x) => x.day === d && !x.is_canary).forEach((doc) => {
        for (let i = 0; i < 2; i++) {
          const s = pick(r, doc.recipients);
          if (!s) continue;
          const nm = this.emp[s].name.split(" ")[0];
          out.push({
            id: "m" + d + "-" + n++, day: d, channel: "email", sender: s,
            subject: doc.title + " follow-up",
            snippet: "Hi, Thanks for circulating " + doc.title + ". I'll fold it into the launch plan by tomorrow. Thanks " + nm
          });
        }
      });
      if (r() < 0.45) {
        out.push({ id: "m" + d + "-" + n++, day: d, channel: "chat", sender: this.w.decoy, subject: "frustrated", snippet: pick(r, ANGRY) });
      }
      return (this.msgCache[d] = out);
    }
    t_search_messages(a) {
      if (!a.query || !a.query.trim()) return bad("invalid arguments");
      if (!this.spend()) return bad("no actions left today");
      const q = a.query.toLowerCase(), f = a.day_from || 1, t = a.day_to || this.day;
      let all = [];
      for (let d = f; d <= Math.min(t, this.day); d++) all = all.concat(this.msgsFor(d));
      const res = all.filter((m) => (m.subject + " " + m.snippet + " " + this.emp[m.sender].name).toLowerCase().includes(q));
      return ok({ messages: res.slice(0, 20) });
    }
    t_read_message(a) {
      if (!this.spend()) return bad("no actions left today");
      const d = parseInt((a.id || "").slice(1), 10);
      const m = this.msgsFor(d).find((x) => x.id === a.id);
      if (!m) return bad("no such message");
      return ok({ message: Object.assign({ body: m.snippet + " " + this.emp[m.sender].name }, m) });
    }
    t_interview(a) {
      if (!this.emp[a.employee] || !TOPICS.includes(a.topic)) return bad("invalid arguments");
      const key = a.employee + a.topic + this.day;
      if (this.ivCache[key]) return ok(this.ivCache[key]);
      if (!this.spend()) return bad("no actions left today");
      const r = rng(hash(this.seed, "iv", key));
      const evasive = r() < (a.employee === this.w.mole ? 0.24 : 0.2);
      let ans;
      if (evasive) ans = pick(r, EVASIVE);
      else if (a.topic === "recent_documents") {
        const h = this.held(a.employee, this.day - 2);
        ans = h.length ? "I opened " + shuffle(r, h).slice(0, 2).map((x) => x.title).join(" and ") + ". Happy to show you my access history." : "The usual stuff, I guess. Why, is something missing?";
      } else ans = pick(r, a.topic === "workload" ? WORK : a.topic === "contacts_outside" ? OUTSIDE : NEEDS);
      const res = { employee: a.employee, topic: a.topic, answer: ans, evasive };
      this.ivCache[key] = res;
      return ok(res);
    }
    t_plant_canary(a) {
      if (this.plantedToday >= 2) return bad("at most 2 canaries per day");
      const ids = Object.keys(a.assignment || {}).filter((i) => this.emp[i] && !this.restricted.has(i));
      const labels = new Set(ids.map((i) => a.assignment[i]));
      if (!ids.length || labels.size > 3 || !a.doc_title) return bad("invalid arguments");
      if (!this.spend()) return bad("no actions left today");
      this.plantedToday++;
      const id = "c" + (this.canaries.length + 1);
      const variants = {};
      ids.forEach((i) => (variants[a.assignment[i]] = (variants[a.assignment[i]] || []).concat(i)));
      const c = { id, title: a.doc_title, day: this.day, assign: Object.fromEntries(ids.map((i) => [i, a.assignment[i]])), variants };
      this.canaries.push(c);
      this.docs.push({ doc_id: id, title: a.doc_title, day: this.day, recipients: ids, is_canary: true });
      this.Vtrue -= 0.01;
      this.costs += 0.01;
      this.events.push({ type: "canary", c });
      return ok({ canary_id: id });
    }
    t_check_leak_feed() {
      if (!this.spend()) return bad("no actions left today");
      return ok({ items: this.feed() });
    }
    feed() {
      return this.leaks.filter((l) => l.surface <= this.day).map((l) => {
        const o = { surfaced_day: l.surface, doc_id: l.doc, title: l.title };
        if (l.variant) o.variant = l.variant;
        return o;
      });
    }
    t_restrict_access(a) {
      if (!this.emp[a.employee]) return bad("invalid arguments");
      if (!this.spend()) return bad("no actions left today");
      this.restricted.add(a.employee);
      return ok({ restricted: [...this.restricted] });
    }
    t_unrestrict_access(a) {
      if (!this.spend()) return bad("no actions left today");
      this.restricted.delete(a.employee);
      return ok({ restricted: [...this.restricted] });
    }
    t_advance_day() {
      const d = this.day;
      const r = rng(hash(this.seed, "leak", d));
      const mole = this.w.mole;
      const elig = this.held(mole, d - 2).filter((x) => !this.leaks.some((l) => l.doc === x.doc_id));
      let leaked = null;
      const forced = this.moleControl ? elig.find((x) => x.doc_id === this.pendingLeak) : null;
      this.pendingLeak = null;
      if (this.moleControl ? forced : elig.length && r() < 0.65) {
        const wts = elig.map((x) => (x.is_canary ? 1 - x.recipients.length / 40 : 1));
        let t = r() * wts.reduce((a, b) => a + b, 0), i = 0;
        while (i < elig.length - 1 && (t -= wts[i]) > 0) i++;
        const doc = forced || elig[i];
        let variant = null;
        if (doc.is_canary) {
          const c = this.canaries.find((x) => x.id === doc.doc_id);
          const mine = c.assign[mole], all = Object.keys(c.variants);
          const others = all.filter((v) => v !== mine);
          variant = r() < 0.95 || !others.length ? mine : pick(r, others);
        }
        leaked = { doc: doc.doc_id, title: doc.title, day: d, surface: d + (r() < 0.5 ? 2 : 3), variant };
        this.leaks.push(leaked);
        this.Vtrue -= 0.05;
      }
      const rc = this.restricted.size * 0.01;
      this.Vtrue -= rc;
      this.costs += rc;
      this.Vtrue = Math.max(0, this.Vtrue);
      const surfaced = this.leaks.filter((l) => l.surface === d + 1);
      this.day++;
      this.actions = 8;
      this.plantedToday = 0;
      this.events.push({ type: "advance", leaked, surfaced });
      if (this.day > 21) {
        this.over = true;
        this.score = 0;
        return ok({ closed_day: d, day: this.day, V: this.V, episode_over: true, reason: "horizon" });
      }
      this.addDay(this.day);
      const nd = this.docs.filter((x) => x.day === this.day && !x.is_canary).map((x) => x.doc_id);
      return ok({ closed_day: d, day: this.day, V: this.V, new_documents: nd });
    }
    t_accuse(a) {
      if (!this.emp[a.employee]) return bad("invalid arguments");
      this.over = true;
      this.accused = a.employee;
      this.correct = a.employee === this.w.mole;
      this.score = this.correct ? r2(Math.max(0, this.Vtrue)) : -1;
      return ok({ accused: a.employee, episode_over: true });
    }
    evidence() {
      const ev = {};
      this.w.employees.forEach((e) => (ev[e.id] = 0));
      this.leaks.filter((l) => l.surface <= this.day).forEach((l) => {
        const doc = this.docs.find((x) => x.doc_id === l.doc);
        let set = doc.recipients;
        if (l.variant) {
          const c = this.canaries.find((x) => x.id === l.doc);
          set = c.variants[l.variant] || [];
        }
        set.forEach((i) => (ev[i] += 1));
      });
      return ev;
    }
  }

  class Hunter {
    constructor(env, seed) {
      this.env = env;
      this.r = rng(hash(seed, "hunter"));
      this.suspects = env.w.employees.map((e) => e.id);
      this.canaryOf = {};
      this.accused = null;
    }
    plant(day) {
      const env = this.env, ord = shuffle(this.r, this.suspects);
      if (ord.length < 2) return;
      const mk = (n, alt) => {
        const asg = {};
        ord.forEach((id, i) => (asg[id] = alt ? (i % 2 ? "B" : "A") : i < Math.ceil(ord.length / 2) ? "A" : "B"));
        const v = window.AD.vocab, tpl = pick(this.r, v.title_templates);
        const title = tpl.replace("{q}", pick(this.r, ["Q1", "Q2", "Q3", "Q4"])).replace("{d}", pick(this.r, v.depts)).replace("{p}", pick(this.r, v.projects));
        env.call("plant_canary", { doc_title: title, assignment: asg });
      };
      mk(0, false);
      if (ord.length >= 4) mk(1, true);
    }
    review() {
      const env = this.env;
      const items = env.feed();
      let s = new Set(env.w.employees.map((e) => e.id));
      items.forEach((it) => {
        const doc = env.docs.find((x) => x.doc_id === it.doc_id);
        let set;
        if (doc.is_canary && it.variant) set = env.canaries.find((c) => c.id === doc.doc_id).variants[it.variant] || [];
        else set = doc.recipients;
        s = new Set([...s].filter((i) => set.includes(i)));
      });
      this.suspects = [...s];
      return this.suspects;
    }
    decide() {
      const sus = this.review();
      if (sus.length === 1 || env_day(this.env) >= 19) {
        const all = this.env.w.employees.map((e) => e.id);
        return sus.length ? sus[Math.floor(this.r() * sus.length)] : all[Math.floor(this.r() * all.length)];
      }
      return null;
    }
  }
  function env_day(e) { return e.day; }

  window.Eng = { rng, hash, poisson, pick, shuffle, r2, Env, Hunter, TOPICS };
})();
