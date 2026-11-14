// Canary browser game: a thin UI over game/canary_game.py running in Pyodide. Owner: HARNESS (WS6).
// The page calls a tool ONLY when the player presses its button (no hidden status calls).
"use strict";

const $ = (id) => document.getElementById(id);
let py = null, game = null, calls = 0, reference = {};

function randomSeed() { return 3000 + Math.floor(Math.random() * 7000); }

async function boot() {
  $("seed").value = new URLSearchParams(location.search).get("seed") || randomSeed();
  try {
    py = await loadPyodide();
    const manifest = await (await fetch("py/manifest.json")).json();
    for (const rel of manifest.files) {
      const text = await (await fetch("py/" + rel)).text();
      const path = "/home/pyodide/" + rel;
      py.FS.mkdirTree(path.substring(0, path.lastIndexOf("/")));
      py.FS.writeFile(path, text);
    }
    py.runPython("import sys; sys.path.insert(0, '/home/pyodide'); import canary_game");
    try { reference = await (await fetch("reference.json")).json(); } catch (_) { reference = {}; }
    $("startBtn").disabled = false;
    $("startBtn").textContent = "Start investigation";
  } catch (e) {
    $("loadMsg").textContent = "Could not load the environment: " + e;
  }
}

function start() {
  const seed = $("seed").value.trim();
  try {
    game = py.runPython(`canary_game.Game(${JSON.stringify(seed)})`);
  } catch (e) {
    $("loadMsg").textContent = String(e).split("\n").filter(Boolean).pop();
    return;
  }
  const spec = JSON.parse(game.spec_json());
  $("rules").textContent = spec.instruction;
  $("ver").textContent = spec.tiers_version;
  $("tools").innerHTML = "";
  for (const t of spec.tools) $("tools").appendChild(toolCard(t));
  $("start").hidden = true;
  $("game").hidden = false;
  log("system", {}, { ok: true, data: { seed: spec.seed, tier: spec.tier } });
}

function field(name, schema, required) {
  const wrap = document.createElement("label");
  wrap.textContent = name + (required ? " *" : "");
  let input;
  if (schema.enum) {
    input = document.createElement("select");
    for (const v of schema.enum) input.add(new Option(v, v));
  } else if (schema.type === "object") {
    input = document.createElement("input");
    input.placeholder = "e01:A, e02:A, e03:B";
    input.dataset.kind = "assignment";
  } else {
    input = document.createElement("input");
    input.type = schema.type === "integer" ? "number" : "text";
    if (schema.description) input.placeholder = schema.description;
  }
  input.name = name;
  input.dataset.type = schema.type;
  wrap.appendChild(input);
  return wrap;
}

function readArgs(form) {
  const args = {};
  for (const el of form.querySelectorAll("input, select")) {
    const v = el.value.trim();
    if (v === "") continue;
    if (el.dataset.kind === "assignment") {
      const obj = {};
      for (const pair of v.split(",")) {
        const [k, val] = pair.split(":").map((s) => (s || "").trim());
        if (k) obj[k] = val;
      }
      args[el.name] = obj;
    } else if (el.dataset.type === "integer") {
      args[el.name] = Number(v);
    } else {
      args[el.name] = v;
    }
  }
  return args;
}

function toolCard(tool) {
  const form = document.createElement("form");
  form.className = "tool card" + (tool.name === "accuse" ? " danger" : "");
  const props = tool.input_schema.properties || {};
  const req = new Set(tool.input_schema.required || []);
  const h = document.createElement("h3");
  h.textContent = tool.name;
  h.title = tool.description;
  form.appendChild(h);
  const d = document.createElement("p");
  d.className = "desc";
  d.textContent = tool.description;
  form.appendChild(d);
  for (const [name, schema] of Object.entries(props)) form.appendChild(field(name, schema, req.has(name)));
  const b = document.createElement("button");
  b.textContent = tool.name === "accuse" ? "Accuse (once, final)" : "Run";
  form.appendChild(b);
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (tool.name === "accuse" && !confirm("Accuse " + (readArgs(form).employee || "?") + "? This ends the investigation.")) return;
    run(tool.name, readArgs(form));
  });
  return form;
}

function run(tool, args) {
  const res = JSON.parse(game.call_json(tool, JSON.stringify(args)));
  calls += 1;
  $("calls").textContent = calls + " tool call" + (calls === 1 ? "" : "s");
  log(tool, args, res);
  if (res.done) finish();
}

function log(tool, args, res) {
  const item = document.createElement("div");
  item.className = "entry " + (res.ok ? "ok" : "err");
  const head = document.createElement("div");
  head.className = "head";
  head.textContent = tool + (Object.keys(args).length ? " " + JSON.stringify(args) : "");
  const body = document.createElement("pre");
  body.textContent = res.ok ? JSON.stringify(res.data, null, 1) : "error: " + res.error;
  item.append(head, body);
  $("log").prepend(item);
}

function fmt(x) { return (x >= 0 ? "+" : "") + Number(x).toFixed(2); }

function finish() {
  for (const b of document.querySelectorAll("#tools button")) b.disabled = true;
  const r = JSON.parse(game.reveal_json());
  const ref = (reference[String(r.seed)] || []);
  const rows = [
    ["You", r.you.score, `${r.you.end_reason === "accused" ? "accused " + r.you.accused + (r.you.correct ? " (correct)" : " (wrong)") : r.you.end_reason}, day ${r.you.final_day}, ${r.you.tool_calls} calls`],
    ["Reference solver", r.solver.score, `${r.solver.correct ? "correct" : "wrong / no accusation"}, day ${r.solver.final_day}, ${r.solver.tool_calls} calls`],
    ...ref.map((a) => [a.agent, a.score, a.note || "committed run, same seed"]),
  ];
  if (!ref.length) rows.push(["gemini-4-carbon", null, "no committed run on this seed yet"]);
  const sec = $("reveal");
  sec.innerHTML = `<h2>The mole was ${r.mole}</h2>
    <table><thead><tr><th>investigator</th><th>score</th><th></th></tr></thead><tbody>${
      rows.map(([who, s, note]) => `<tr><td>${who}</td><td class="num">${s === null ? "–" : fmt(s)}</td><td class="muted">${note}</td></tr>`).join("")
    }</tbody></table>
    <p class="muted">Score = company value left at a correct accusation, −1 for a wrong one, 0 for none. Seed ${r.seed}, medium, tiers ${r.tiers_version}.</p>
    <p><button id="again">Play another seed</button> <button id="dl">Download my actions (JSON)</button></p>`;
  sec.hidden = false;
  $("again").onclick = () => { location.search = "?seed=" + randomSeed(); };
  $("dl").onclick = () => {
    const blob = new Blob([game.actions_json()], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `canary-seed-${r.seed}-actions.json`;
    a.click();
  };
  sec.scrollIntoView({ behavior: "smooth" });
}

$("startBtn").addEventListener("click", start);
boot();
