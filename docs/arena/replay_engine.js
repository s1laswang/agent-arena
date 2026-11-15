const TIER_DEFAULTS = {
  easy: {
    n_days: 14,
    n_employees: 12,
    canary_cost: 0.01,
    restrict_cost_per_day: 0.01,
    leak_damage: 0.05,
    tool_call_cap: 300,
  },
  medium: {
    n_days: 14,
    n_employees: 20,
    canary_cost: 0.01,
    restrict_cost_per_day: 0.01,
    leak_damage: 0.04,
    tool_call_cap: 300,
  },
  hard: {
    n_days: 21,
    n_employees: 40,
    canary_cost: 0.01,
    restrict_cost_per_day: 0.01,
    leak_damage: 0.05,
    tool_call_cap: 420,
  },
};

const KNOWN_TIERS = new Set(["easy", "medium", "hard"]);

const FORBIDDEN_PRE_END_KEYS = new Set([
  "mole",
  "true_mole",
  "moleId",
  "mole_id",
  "decoy",
  "true_decoy",
  "decoyId",
  "decoy_id",
  "correct",
  "accused_correct",
  "true_v",
  "true_V",
  "trueV",
  "score",
  "score_fmt",
  "formattedScore",
  "world_seed",
  "_world",
  "is_canary",
  "is_mole",
  "leaking_sprite_employee",
  "mole_sprite",
  "culprit_sprite",
  "leaker_employee",
  "sealed_verdict",
  "sealed_reveal",
  "sealed_reveal_b64",
  "solver_sealed_reveal_b64",
  "verdict",
  "reveal",
  "outcome",
  "terminal",
  "post_game",
  "post_end",
]);

function getGlobalRoot() {
  return typeof globalThis !== "undefined" ? globalThis : {};
}

function round10(x) {
  const num = Number(x);
  if (!Number.isFinite(num)) return 0;
  return Math.round(num * 1e10) / 1e10;
}

export function fmtScore(x) {
  const num = Number(x);
  if (!Number.isFinite(num)) return "0.00";
  const rounded = Math.round(num * 100) / 100;
  if (rounded === 0) return "0.00";
  const sign = rounded > 0 ? "+" : "-";
  return sign + Math.abs(rounded).toFixed(2);
}

function isFiniteNumber(val) {
  return typeof val === "number" && Number.isFinite(val);
}

function toFiniteNumber(val, fallback) {
  if (val === null || val === undefined || val === "" || typeof val === "boolean") {
    return fallback;
  }
  const num = Number(val);
  return Number.isFinite(num) ? num : fallback;
}

function clonePlain(input) {
  if (input === null || input === undefined) return input;
  if (Array.isArray(input)) return input.map((item) => clonePlain(item));
  if (typeof input !== "object") return input;
  const out = {};
  for (const [k, v] of Object.entries(input)) {
    out[k] = clonePlain(v);
  }
  return out;
}

function scrubPreEndObject(input) {
  if (input === null || input === undefined) return input;
  if (Array.isArray(input)) return input.map((item) => scrubPreEndObject(item));
  if (typeof input !== "object") return input;
  const out = {};
  for (const [k, v] of Object.entries(input)) {
    if (FORBIDDEN_PRE_END_KEYS.has(k)) continue;
    out[k] = scrubPreEndObject(v);
  }
  return out;
}

function canonicalizeAgent(rawAgent) {
  if (!rawAgent) return "gemini";
  const s = String(rawAgent).trim().toLowerCase();
  if (!s) return "gemini";
  if (s.includes("solver") || s === "bayesian" || s === "reference") {
    return "solver";
  }
  if (
    s === "gemini" ||
    s.includes("gemini") ||
    s.includes("opencode") ||
    s.includes("inproc")
  ) {
    return "gemini";
  }
  return s;
}

function defaultAgentLabel(canonicalAgent, rawAgent) {
  if (rawAgent && typeof rawAgent === "string" && rawAgent.trim()) {
    const trimmed = rawAgent.trim();
    if (trimmed !== "gemini" && trimmed !== "solver") return trimmed;
  }
  if (canonicalAgent === "solver") return "SolverPolicy";
  if (canonicalAgent === "gemini") return "opencode:google/gemini-4-carbon";
  return String(canonicalAgent || "gemini");
}

function normalizeTier(rawTier) {
  const s = String(rawTier || "hard").trim().toLowerCase();
  if (KNOWN_TIERS.has(s)) return s;
  if (s.startsWith("hard")) return "hard";
  if (s.startsWith("medium")) return "medium";
  if (s.startsWith("easy")) return "easy";
  return "hard";
}

function decodeBase64Utf8(b64Text) {
  if (typeof b64Text !== "string" || !b64Text.trim()) return null;
  let clean = b64Text.trim();
  if (clean.startsWith("b64:")) clean = clean.slice(4).trim();
  if (clean.startsWith("sealed:")) clean = clean.slice(7).trim();
  try {
    const g = getGlobalRoot();
    if (g.Buffer && typeof g.Buffer.from === "function") {
      return g.Buffer.from(clean, "base64").toString("utf8");
    }
    if (typeof g.atob === "function") {
      const bin = g.atob(clean);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i += 1) {
        bytes[i] = bin.charCodeAt(i);
      }
      if (typeof g.TextDecoder === "function") {
        return new g.TextDecoder("utf-8").decode(bytes);
      }
      return bin;
    }
  } catch (_) {
    return null;
  }
  return null;
}

function tryParseSealedPayload(token) {
  if (!token) return null;
  if (typeof token === "object") return clonePlain(token);
  if (typeof token !== "string") return null;
  const trimmed = token.trim();
  if (!trimmed || trimmed === "[SEALED]" || trimmed.startsWith("sha256:")) {
    return null;
  }
  if (trimmed.startsWith("{")) {
    try {
      return JSON.parse(trimmed);
    } catch (_) {
      return null;
    }
  }
  const decoded = decodeBase64Utf8(trimmed);
  if (decoded && decoded.trim().startsWith("{")) {
    try {
      return JSON.parse(decoded);
    } catch (_) {
      return null;
    }
  }
  return null;
}

function buildStepSummary(tool, args, resData, ok, isSealedAccuse) {
  if (isSealedAccuse || tool === "accuse") {
    if (isSealedAccuse) return "Accusation filed [SEALED]";
    const target =
      (args && typeof args === "object" && args.employee) ||
      (resData && typeof resData === "object" && resData.accused) ||
      "";
    if (target && target !== "[SEALED]") return `Accused ${target}`;
    return "Accusation filed";
  }
  if (!ok) return `${tool} (rejected)`;
  const a = args && typeof args === "object" ? args : {};
  const d = resData && typeof resData === "object" ? resData : {};
  switch (tool) {
    case "list_employees": {
      const count = Array.isArray(d.employees) ? d.employees.length : null;
      return count !== null ? `Listed ${count} employees` : "Listed employees";
    }
    case "status": {
      const vPart = isFiniteNumber(d.V) ? `, V=${Number(d.V).toFixed(2)}` : "";
      const dayPart = isFiniteNumber(d.day) ? `Day ${d.day}` : "status";
      return `Checked status (${dayPart}${vPart})`;
    }
    case "advance_day": {
      if (d.episode_over) return `Closed Day ${d.closed_day || ""}`.trim();
      const nextDay = isFiniteNumber(d.day) ? d.day : null;
      const vPart = isFiniteNumber(d.V) ? ` (V=${Number(d.V).toFixed(2)})` : "";
      return nextDay !== null ? `Advanced to Day ${nextDay}${vPart}` : "Advanced day";
    }
    case "plant_canary": {
      const cid = d.canary_id || a.doc_title || "canary";
      const asgCount =
        a.assignment && typeof a.assignment === "object"
          ? Object.keys(a.assignment).length
          : null;
      return asgCount !== null
        ? `Planted canary ${cid} (${asgCount} recipients)`
        : `Planted canary ${cid}`;
    }
    case "check_leak_feed": {
      const n = Array.isArray(d.items) ? d.items.length : null;
      return n !== null
        ? `Checked leak feed (${n} surfaced)`
        : "Checked leak feed";
    }
    case "list_documents": {
      const from = a.day_from !== undefined ? a.day_from : "?";
      const to = a.day_to !== undefined ? a.day_to : from;
      return `Listed documents (Day ${from}..${to})`;
    }
    case "read_access_logs": {
      const from = a.day_from !== undefined ? a.day_from : "?";
      const to = a.day_to !== undefined ? a.day_to : from;
      return `Read access logs (Day ${from}..${to})`;
    }
    case "search_messages": {
      const q = a.query !== undefined ? String(a.query) : "";
      return q ? `Searched messages (${q})` : "Searched messages";
    }
    case "read_message": {
      const mid = a.message_id || d.id || "";
      return mid ? `Read message ${mid}` : "Read message";
    }
    case "interview": {
      const emp = a.employee || "";
      const topic = a.topic ? ` (${a.topic})` : "";
      return emp ? `Interviewed ${emp}${topic}` : `Interview${topic}`;
    }
    case "restrict_access": {
      const emp = d.restricted || a.employee || "";
      return emp ? `Restricted access for ${emp}` : "Restricted access";
    }
    case "unrestrict_access": {
      const emp = d.unrestricted || a.employee || "";
      return emp ? `Unrestricted access for ${emp}` : "Unrestricted access";
    }
    default:
      return String(tool || "step");
  }
}

function sanitizeEmployeesList(rawList) {
  if (!Array.isArray(rawList)) return [];
  const out = [];
  for (const item of rawList) {
    if (!item || typeof item !== "object" || !item.id) continue;
    const dept = String(item.dept || item.department || "");
    const clean = {
      id: String(item.id),
      name: String(item.name || item.id),
      dept,
      department: String(item.department || item.dept || dept),
    };
    if (item.role !== undefined) clean.role = String(item.role);
    if (isFiniteNumber(item.clearance)) clean.clearance = Number(item.clearance);
    out.push(clean);
  }
  return out;
}

function normalizeTrackSteps(rawSteps, tier) {
  const params = TIER_DEFAULTS[tier] || TIER_DEFAULTS.hard;
  const steps = Array.isArray(rawSteps) ? rawSteps : [];
  let runningKnownV = 1.0;
  const restricted = new Set();
  let extractedEmployees = [];
  const normalized = [];

  for (let idx = 0; idx < steps.length; idx += 1) {
    const st = steps[idx];
    if (!st || typeof st !== "object") continue;

    const tool = String(st.tool || "");
    const rawArgs =
      st.args && typeof st.args === "object"
        ? clonePlain(st.args)
        : st.arguments && typeof st.arguments === "object"
          ? clonePlain(st.arguments)
          : {};
    const hasResultObj = Boolean(st.result && typeof st.result === "object");
    const resObj = hasResultObj ? st.result : null;
    const resData =
      resObj && resObj.data && typeof resObj.data === "object" ? resObj.data : null;
    const ok =
      typeof st.ok === "boolean"
        ? st.ok
        : resObj && typeof resObj.ok === "boolean"
          ? resObj.ok
          : true;

    if (ok && tool === "list_employees" && resData && Array.isArray(resData.employees) && !extractedEmployees.length) {
      extractedEmployees = sanitizeEmployeesList(resData.employees);
    }

    if (ok) {
      if (tool === "plant_canary") {
        runningKnownV = round10(Math.max(0.0, runningKnownV - params.canary_cost));
      } else if (tool === "restrict_access") {
        const emp = (resData && resData.restricted) || rawArgs.employee;
        if (emp && typeof emp === "string") restricted.add(emp);
      } else if (tool === "unrestrict_access") {
        const emp = (resData && resData.unrestricted) || rawArgs.employee;
        if (emp && typeof emp === "string") restricted.delete(emp);
      } else if (tool === "advance_day") {
        if (resData && isFiniteNumber(resData.V)) {
          runningKnownV = round10(Number(resData.V));
        } else if (hasResultObj) {
          runningKnownV = round10(
            Math.max(0.0, runningKnownV - params.restrict_cost_per_day * restricted.size)
          );
        }
      } else if (tool === "status" && resData && isFiniteNumber(resData.V)) {
        runningKnownV = round10(Number(resData.V));
      }
    }

    let stepKnownV = runningKnownV;
    if (isFiniteNumber(st.known_v)) {
      stepKnownV = round10(Number(st.known_v));
      runningKnownV = stepKnownV;
    } else if (isFiniteNumber(st.known_V)) {
      stepKnownV = round10(Number(st.known_V));
      runningKnownV = stepKnownV;
    } else if (isFiniteNumber(st.visible_v)) {
      stepKnownV = round10(Number(st.visible_v));
      runningKnownV = stepKnownV;
    } else if (isFiniteNumber(st.visible_V)) {
      stepKnownV = round10(Number(st.visible_V));
      runningKnownV = stepKnownV;
    } else if (!hasResultObj && isFiniteNumber(st.V)) {
      stepKnownV = round10(Number(st.V));
      runningKnownV = stepKnownV;
    }

    const day = Math.max(1, Math.trunc(toFiniteNumber(st.day, 1)));
    const callIdx = Math.trunc(
      toFiniteNumber(st.call_idx, toFiniteNumber(st.t, idx))
    );
    const tVal = Math.trunc(
      toFiniteNumber(st.t, toFiniteNumber(st.call_idx, idx))
    );

    const rawSummary =
      typeof st.summary === "string" && st.summary.trim()
        ? st.summary.trim()
        : null;

    let unsealedAccused = null;
    if (tool === "accuse") {
      const cand =
        rawArgs.employee ||
        (resData && resData.accused) ||
        (typeof st.accused === "string" ? st.accused : null);
      if (cand && cand !== "[SEALED]") {
        unsealedAccused = String(cand);
      }
    }

    const unsealedSummary =
      tool === "accuse"
        ? unsealedAccused
          ? `Accused ${unsealedAccused}`
          : rawSummary && rawSummary !== "[SEALED]" && !rawSummary.includes("[SEALED]")
            ? rawSummary
            : "Accusation filed"
        : rawSummary || buildStepSummary(tool, rawArgs, resData, ok, false);

    const rawCommentary =
      typeof st.commentary === "string" && st.commentary.trim()
        ? st.commentary.trim()
        : null;

    normalized.push({
      day,
      call_idx: callIdx,
      t: tVal,
      tool,
      rawArgs,
      ok,
      known_v: stepKnownV,
      unsealedAccused,
      unsealedSummary,
      commentary: rawCommentary,
    });
  }

  return { steps: normalized, employees: extractedEmployees };
}

function summarizePublicStepCounts(steps) {
  let canariesPlanted = 0;
  let interviewsDone = 0;
  const restrictedSet = new Set();
  for (const s of steps) {
    if (!s || s.ok === false) continue;
    if (s.tool === "plant_canary") canariesPlanted += 1;
    else if (s.tool === "interview") interviewsDone += 1;
    else if (s.tool === "restrict_access" && s.args && s.args.employee) {
      restrictedSet.add(s.args.employee);
    } else if (s.tool === "unrestrict_access" && s.args && s.args.employee) {
      restrictedSet.delete(s.args.employee);
    }
  }
  return {
    canaries_planted: canariesPlanted,
    interviews_done: interviewsDone,
    restricted_count: restrictedSet.size,
    tool_calls_so_far: steps.length,
  };
}

function parseEpisodeKeyString(keyStr, fallbackTier = "hard") {
  const s = String(keyStr || "").trim();
  const parts = s.split(":");
  if (parts.length >= 2 && KNOWN_TIERS.has(parts[0].toLowerCase())) {
    const tier = normalizeTier(parts[0]);
    const seed = Number(parts[1]);
    const agent = parts.length >= 3 ? parts.slice(2).join(":") : null;
    if (Number.isFinite(seed)) {
      return { tier, seed: Math.trunc(seed), agent };
    }
  }
  const numericSeed = Number(s);
  if (s !== "" && Number.isFinite(numericSeed)) {
    return { tier: normalizeTier(fallbackTier), seed: Math.trunc(numericSeed), agent: null };
  }
  return null;
}

function extractPostEndMetaFromRaw(rawEp, canonicalAgent, steps, sourcePack, tier, seed) {
  let sealedObj = null;
  if (sourcePack && typeof sourcePack === "object") {
    if (typeof sourcePack.unlockPostGameReveal === "function") {
      try {
        const unlocked = sourcePack.unlockPostGameReveal(tier, seed, true, canonicalAgent);
        if (unlocked && typeof unlocked === "object") {
          if (
            canonicalAgent === "solver" &&
            unlocked.solver &&
            typeof unlocked.solver === "object"
          ) {
            sealedObj = Object.assign(
              {
                mole: unlocked.mole ?? null,
                mole_name: unlocked.mole_name || "",
                mole_dept: unlocked.mole_dept || "",
              },
              unlocked.solver
            );
          } else if (
            canonicalAgent === "gemini" &&
            unlocked.gemini &&
            typeof unlocked.gemini === "object"
          ) {
            sealedObj = Object.assign(
              {
                mole: unlocked.mole ?? null,
                mole_name: unlocked.mole_name || "",
                mole_dept: unlocked.mole_dept || "",
              },
              unlocked.gemini
            );
          } else if (canonicalAgent !== "solver" || !unlocked.solver) {
            sealedObj = clonePlain(unlocked);
          }
        }
      } catch (_) {}
    }
    if (!sealedObj && typeof sourcePack.unsealReveal === "function") {
      try {
        const token =
          canonicalAgent === "solver"
            ? rawEp.solver_sealed_reveal_b64 || rawEp.sealed_reveal_b64 || rawEp
            : rawEp.sealed_reveal_b64 || rawEp;
        const unsealed = sourcePack.unsealReveal(token);
        if (unsealed && typeof unsealed === "object") {
          if (
            canonicalAgent === "solver" &&
            unsealed.solver &&
            typeof unsealed.solver === "object"
          ) {
            sealedObj = Object.assign(
              {
                mole: unsealed.mole ?? null,
                mole_name: unsealed.mole_name || "",
                mole_dept: unsealed.mole_dept || "",
              },
              unsealed.solver
            );
          } else {
            sealedObj = clonePlain(unsealed);
          }
        }
      } catch (_) {}
    }
  }

  if (!sealedObj) {
    const candidates =
      canonicalAgent === "solver"
        ? [
            rawEp.solver_final,
            rawEp.solver_verdict,
            rawEp.solver_sealed_reveal_b64,
            rawEp.solver_sealed_reveal,
            rawEp.final,
            rawEp.sealed_verdict,
            rawEp.verdict,
            rawEp.sealed_reveal_b64,
            rawEp.sealed_reveal,
          ]
        : [
            rawEp.final,
            rawEp.sealed_verdict,
            rawEp.verdict,
            rawEp.sealed_reveal_b64,
            rawEp.sealed_reveal,
            rawEp.reveal,
          ];
    for (const cand of candidates) {
      const parsed = tryParseSealedPayload(cand);
      if (parsed && typeof parsed === "object" && !parsed.sealed) {
        if (
          canonicalAgent === "solver" &&
          parsed.solver &&
          typeof parsed.solver === "object" &&
          rawEp.steps &&
          rawEp.solver_steps
        ) {
          sealedObj = Object.assign(
            {
              mole: parsed.mole ?? null,
              mole_name: parsed.mole_name || "",
              mole_dept: parsed.mole_dept || "",
            },
            parsed.solver
          );
        } else {
          sealedObj = parsed;
        }
        break;
      }
    }
  }

  const meta = Object.assign({}, sealedObj || {});
  const pickDef = (...vals) => {
    for (const v of vals) {
      if (v !== undefined) return v;
    }
    return undefined;
  };

  const accuseStep = steps.find((s) => s.tool === "accuse") || null;
  const lastStep = steps.length ? steps[steps.length - 1] : null;
  const isDualEp = Boolean(Array.isArray(rawEp.steps) && Array.isArray(rawEp.solver_steps));

  const epAccused =
    canonicalAgent === "solver"
      ? isDualEp
        ? rawEp.solver_accused
        : rawEp.solver_accused ?? rawEp.accused
      : rawEp.accused;
  const epFinalDay =
    canonicalAgent === "solver"
      ? isDualEp
        ? rawEp.solver_final_day
        : rawEp.solver_final_day ?? rawEp.final_day ?? rawEp.finalDay
      : rawEp.final_day ?? rawEp.finalDay;
  const epToolCalls =
    canonicalAgent === "solver"
      ? isDualEp
        ? rawEp.solver_tool_calls
        : rawEp.solver_tool_calls ?? rawEp.tool_calls
      : rawEp.tool_calls;
  const epScore =
    canonicalAgent === "solver"
      ? isDualEp
        ? rawEp.solver_score
        : rawEp.solver_score ?? rawEp.score
      : rawEp.score;
  const epCorrect =
    canonicalAgent === "solver"
      ? isDualEp
        ? rawEp.solver_correct
        : rawEp.solver_correct ?? rawEp.correct
      : rawEp.correct;
  const epEndReason =
    canonicalAgent === "solver"
      ? isDualEp
        ? rawEp.solver_end_reason
        : rawEp.solver_end_reason ?? rawEp.end_reason
      : rawEp.end_reason;

  let accused = pickDef(
    meta.accused,
    epAccused,
    accuseStep ? accuseStep.unsealedAccused : undefined,
    null
  );
  if (accused === "[SEALED]" || accused === "") accused = null;

  const finalDay = Math.max(
    1,
    Math.trunc(
      toFiniteNumber(
        pickDef(
          meta.final_day,
          meta.finalDay,
          epFinalDay,
          accuseStep ? accuseStep.day : undefined,
          lastStep ? lastStep.day : undefined
        ),
        1
      )
    )
  );

  const toolCalls = Math.max(
    0,
    Math.trunc(
      toFiniteNumber(
        pickDef(
          meta.tool_calls,
          meta.toolCalls,
          epToolCalls,
          steps.length
        ),
        steps.length
      )
    )
  );

  const score = toFiniteNumber(
    pickDef(
      meta.score,
      epScore
    ),
    0
  );

  const moleRaw = pickDef(
    meta.mole,
    meta.true_mole,
    meta.mole_id,
    rawEp.mole,
    rawEp.true_mole,
    rawEp.mole_id,
    null
  );
  const mole = moleRaw && moleRaw !== "[SEALED]" ? String(moleRaw) : null;

  let correctRaw = pickDef(
    meta.correct,
    meta.accused_correct,
    epCorrect
  );
  if (typeof correctRaw !== "boolean") {
    if (mole && accused) {
      correctRaw = accused === mole;
    } else if (!accused) {
      correctRaw = false;
    } else {
      correctRaw = score > 0;
    }
  }

  const endReason = String(
    pickDef(
      meta.end_reason,
      meta.endReason,
      epEndReason,
      accused || accuseStep ? "accused" : "horizon"
    ) || (accused || accuseStep ? "accused" : "horizon")
  );

  const nestedSolver =
    canonicalAgent === "gemini" && meta.solver && typeof meta.solver === "object"
      ? clonePlain(meta.solver)
      : null;

  return {
    score,
    accused,
    mole,
    mole_name: String(meta.mole_name || rawEp.mole_name || ""),
    mole_dept: String(meta.mole_dept || rawEp.mole_dept || ""),
    correct: Boolean(correctRaw),
    end_reason: endReason,
    final_day: finalDay,
    tool_calls: toolCalls,
    nestedSolver,
  };
}

function formatActorClause(label, rec, isGemini) {
  if (!rec) return null;
  const sc = fmtScore(rec.score);
  const day = Math.trunc(toFiniteNumber(rec.final_day, 0));
  if (rec.correct) return `${label} ${sc} (Day ${day})`;
  if (rec.accused) {
    const tag = isGemini ? "Fooled " : "Wrong ";
    return `${label} ${sc} (${tag}Day ${day})`;
  }
  return `${label} ${sc} (Horizon Day ${day})`;
}

function computeFirstCatchFromContenders(youRec, solverRec, geminiRec) {
  const candidates = [];
  if (youRec && youRec.correct === true) {
    candidates.push({
      label: "You",
      key: "human",
      day: toFiniteNumber(youRec.final_day, 999),
      prio: 1,
    });
  }
  if (solverRec && solverRec.correct === true) {
    candidates.push({
      label: "Solver",
      key: "solver",
      day: toFiniteNumber(solverRec.final_day, 999),
      prio: 2,
    });
  }
  if (geminiRec && geminiRec.correct === true) {
    candidates.push({
      label: "Gemini",
      key: "gemini",
      day: toFiniteNumber(geminiRec.final_day, 999),
      prio: 3,
    });
  }
  if (!candidates.length) return "None";
  candidates.sort((a, b) => (a.day !== b.day ? a.day - b.day : a.prio - b.prio));
  return candidates[0].label;
}

function computeWinnerFromContenders(youRec, geminiRec, solverRec) {
  const entries = [];
  if (youRec) entries.push({ key: "human", label: "You", rec: youRec, prio: 1 });
  if (solverRec) entries.push({ key: "solver", label: "Solver", rec: solverRec, prio: 2 });
  if (geminiRec) entries.push({ key: "gemini", label: "Gemini", rec: geminiRec, prio: 3 });
  if (!entries.length) return { winner: "none", winnerLabel: "None" };

  entries.sort((a, b) => {
    const sa = toFiniteNumber(a.rec.score, -999);
    const sb = toFiniteNumber(b.rec.score, -999);
    if (Math.abs(sa - sb) > 1e-9) return sb - sa;
    const ca = a.rec.correct ? 1 : 0;
    const cb = b.rec.correct ? 1 : 0;
    if (ca !== cb) return cb - ca;
    if (ca === 1 && cb === 1) {
      const da = toFiniteNumber(a.rec.final_day, 999);
      const db = toFiniteNumber(b.rec.final_day, 999);
      if (da !== db) return da - db;
    }
    const ta = toFiniteNumber(a.rec.tool_calls, 9999);
    const tb = toFiniteNumber(b.rec.tool_calls, 9999);
    if (ta !== tb) return ta - tb;
    return a.prio - b.prio;
  });

  return { winner: entries[0].key, winnerLabel: entries[0].label };
}

export class CanaryReplayEngine {
  constructor(pack = undefined, opts = {}) {
    this._opts = opts && typeof opts === "object" ? Object.assign({}, opts) : {};
    this._worlds = new Map();
    this._trackMap = new Map();
    this._defaultSeedsByTier = new Map();
    this._sourcePack = null;
    this._explicitPackProvided = pack !== undefined;
    this._lastAutoGlobalRef = null;
    this._selectedTier = normalizeTier(this._opts.tier || "hard");
    this._selectedSeed = null;
    this._currentDay = 1;
    this._humanDone = false;

    if (pack !== undefined && pack !== null) {
      this._ingestSource(pack, this._opts);
    } else if (!this._explicitPackProvided) {
      this._syncAutoGlobalPack();
    }

    const extraSources = [
      this._opts.solverJsonl,
      this._opts.solverPack,
      this._opts.solverReplays,
      this._opts.extraJsonl,
      this._opts.extraPack,
    ];
    for (const extra of extraSources) {
      if (extra !== undefined && extra !== null) {
        this._ingestSource(extra, Object.assign({}, this._opts, { defaultAgent: "solver" }));
      }
    }
  }

  _syncAutoGlobalPack() {
    if (this._explicitPackProvided) return;
    const g = getGlobalRoot();
    const globalPack = g.CANARY_DUEL_PACK || g.CANARY_GEMINI_REPLAYS || null;
    if (globalPack && globalPack !== this._lastAutoGlobalRef) {
      this._worlds.clear();
      this._trackMap.clear();
      this._defaultSeedsByTier.clear();
      this._lastAutoGlobalRef = globalPack;
      this._ingestSource(globalPack, this._opts);
    }
  }

  _ensureWorld(tier, seed, maxDaysHint, employeesHint) {
    const normTier = normalizeTier(tier);
    const normSeed = Math.trunc(Number(seed));
    const worldKey = `${normTier}:${normSeed}`;
    let world = this._worlds.get(worldKey);
    if (!world) {
      const defaults = TIER_DEFAULTS[normTier] || TIER_DEFAULTS.hard;
      world = {
        key: worldKey,
        tier: normTier,
        seed: normSeed,
        maxDays: Math.max(1, Math.trunc(toFiniteNumber(maxDaysHint, defaults.n_days))),
        employees: sanitizeEmployeesList(employeesHint),
        tracks: {},
        inferredMole: null,
        inferredMoleName: "",
        inferredMoleDept: "",
      };
      this._worlds.set(worldKey, world);
    } else {
      if (isFiniteNumber(maxDaysHint) && Number(maxDaysHint) > 0) {
        world.maxDays = Math.trunc(Number(maxDaysHint));
      }
      if (!world.employees.length && Array.isArray(employeesHint) && employeesHint.length) {
        world.employees = sanitizeEmployeesList(employeesHint);
      }
    }
    if (this._selectedSeed === null) {
      this._selectedTier = normTier;
      this._selectedSeed = normSeed;
    }
    return world;
  }

  _registerTrack(tier, seed, rawAgent, rawSteps, rawEp, sourcePack) {
    const normTier = normalizeTier(tier);
    const normSeed = Math.trunc(Number(seed));
    const canonical = canonicalizeAgent(rawAgent);
    const agentLabel = defaultAgentLabel(canonical, rawAgent);
    const maxDaysHint =
      rawEp.maxDays ?? rawEp.max_days ?? rawEp.n_days ?? rawEp.nDays ?? undefined;
    const { steps, employees } = normalizeTrackSteps(rawSteps, normTier);
    const world = this._ensureWorld(
      normTier,
      normSeed,
      maxDaysHint,
      Array.isArray(rawEp.employees) && rawEp.employees.length ? rawEp.employees : employees
    );

    const track = {
      tier: normTier,
      seed: normSeed,
      canonicalAgent: canonical,
      agentLabel,
      steps,
      rawEp,
      sourcePack: sourcePack || this._sourcePack,
      cachedPostEnd: null,
    };

    const existing = world.tracks[canonical];
    if (!existing || (steps.length >= existing.steps.length)) {
      world.tracks[canonical] = track;
    }
    this._trackMap.set(`${normTier}:${normSeed}:${canonical}`, world.tracks[canonical]);
    if (rawAgent && typeof rawAgent === "string") {
      this._trackMap.set(`${normTier}:${normSeed}:${rawAgent.trim()}`, world.tracks[canonical]);
    }
  }

  _ingestEpisodeEntry(rawEp, keyHint, opts, sourcePack) {
    if (!rawEp || typeof rawEp !== "object") return;
    const parsedKey = keyHint ? parseEpisodeKeyString(keyHint, opts.tier || "hard") : null;
    const tier = normalizeTier(
      rawEp.tier || (parsedKey && parsedKey.tier) || opts.tier || "hard"
    );
    const seedVal =
      rawEp.seed !== undefined
        ? Number(rawEp.seed)
        : parsedKey && Number.isFinite(parsedKey.seed)
          ? parsedKey.seed
          : NaN;
    if (!Number.isFinite(seedVal)) return;
    const seed = Math.trunc(seedVal);

    this._ensureWorld(
      tier,
      seed,
      rawEp.maxDays ?? rawEp.max_days ?? rawEp.n_days ?? rawEp.nDays,
      rawEp.employees
    );

    const subGemini =
      (rawEp.gemini && typeof rawEp.gemini === "object" && Array.isArray(rawEp.gemini.steps)
        ? rawEp.gemini
        : null) ||
      (rawEp["opencode-gemini-4-carbon"] &&
      typeof rawEp["opencode-gemini-4-carbon"] === "object"
        ? rawEp["opencode-gemini-4-carbon"]
        : null) ||
      (rawEp.tracks && rawEp.tracks.gemini && typeof rawEp.tracks.gemini === "object"
        ? rawEp.tracks.gemini
        : null);

    const subSolver =
      (rawEp.solver && typeof rawEp.solver === "object" && Array.isArray(rawEp.solver.steps)
        ? rawEp.solver
        : null) ||
      (rawEp.tracks && rawEp.tracks.solver && typeof rawEp.tracks.solver === "object"
        ? rawEp.tracks.solver
        : null);

    if (subGemini) {
      this._registerTrack(
        tier,
        seed,
        subGemini.agent || "gemini",
        subGemini.steps || [],
        Object.assign({ tier, seed, mole: rawEp.mole }, subGemini),
        sourcePack
      );
    }

    if (subSolver) {
      this._registerTrack(
        tier,
        seed,
        subSolver.agent || "solver",
        subSolver.steps || [],
        Object.assign({ tier, seed, mole: rawEp.mole }, subSolver),
        sourcePack
      );
    }

    if (Array.isArray(rawEp.steps)) {
      const explicitAgent =
        rawEp.agent ||
        (parsedKey && parsedKey.agent) ||
        opts.defaultAgent ||
        opts.agent ||
        "gemini";
      this._registerTrack(tier, seed, explicitAgent, rawEp.steps, rawEp, sourcePack);
    }

    if (Array.isArray(rawEp.solver_steps)) {
      this._registerTrack(tier, seed, "solver", rawEp.solver_steps, rawEp, sourcePack);
    }
  }

  _ingestSource(source, opts = {}) {
    if (source === null || source === undefined) return;

    if (typeof source === "string") {
      const trimmed = source.trim();
      if (!trimmed) return;
      if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
        try {
          const parsedWhole = JSON.parse(trimmed);
          this._ingestSource(parsedWhole, opts);
          return;
        } catch (_) {
          const lines = trimmed.split(/\r?\n/);
          for (const line of lines) {
            const ln = line.trim();
            if (!ln) continue;
            const row = JSON.parse(ln);
            this._ingestEpisodeEntry(row, null, opts, null);
          }
          return;
        }
      }
      return;
    }

    if (Array.isArray(source)) {
      for (const item of source) {
        this._ingestEpisodeEntry(item, null, opts, null);
      }
      return;
    }

    if (typeof source === "object") {
      if (
        Array.isArray(source.steps) &&
        source.seed !== undefined &&
        !source.episodes &&
        !source.by_agent
      ) {
        this._ingestEpisodeEntry(source, null, opts, null);
        return;
      }

      this._sourcePack = source;

      if (Array.isArray(source.default_seeds)) {
        const defTier = normalizeTier(source.default_tier || opts.tier || "hard");
        const cleanSeeds = source.default_seeds
          .map((s) => Number(s))
          .filter((s) => Number.isFinite(s))
          .map((s) => Math.trunc(s));
        if (cleanSeeds.length) {
          this._defaultSeedsByTier.set(defTier, cleanSeeds);
        }
      }

      if (source.seeds_by_tier && typeof source.seeds_by_tier === "object") {
        for (const [tKey, arr] of Object.entries(source.seeds_by_tier)) {
          if (Array.isArray(arr)) {
            const clean = arr
              .map((s) => Number(s))
              .filter((s) => Number.isFinite(s))
              .map((s) => Math.trunc(s));
            this._defaultSeedsByTier.set(normalizeTier(tKey), clean);
          }
        }
      }

      if (source.episodes) {
        if (Array.isArray(source.episodes)) {
          for (const ep of source.episodes) {
            this._ingestEpisodeEntry(ep, null, opts, source);
          }
        } else if (typeof source.episodes === "object") {
          const allKeys = Object.getOwnPropertyNames(source.episodes);
          for (const k of allKeys) {
            const val = source.episodes[k];
            if (val && typeof val === "object") {
              this._ingestEpisodeEntry(val, k, opts, source);
            }
          }
        }
      }

      if (source.by_agent && typeof source.by_agent === "object") {
        const agentKeys = Object.getOwnPropertyNames(source.by_agent);
        for (const k of agentKeys) {
          const val = source.by_agent[k];
          if (val && typeof val === "object") {
            this._ingestEpisodeEntry(val, k, opts, source);
          }
        }
      }

      if (Array.isArray(source.replays)) {
        for (const ep of source.replays) {
          this._ingestEpisodeEntry(ep, null, opts, source);
        }
      }
    }
  }

  _resolvePostEndForWorld(world) {
    if (!world) return;
    const trackNames = Object.keys(world.tracks);
    for (const tName of trackNames) {
      const tr = world.tracks[tName];
      if (!tr.cachedPostEnd) {
        tr.cachedPostEnd = extractPostEndMetaFromRaw(
          tr.rawEp,
          tr.canonicalAgent,
          tr.steps,
          tr.sourcePack || this._sourcePack,
          world.tier,
          world.seed
        );
      }
      const meta = tr.cachedPostEnd;
      if (!world.inferredMole) {
        if (meta.mole) {
          world.inferredMole = meta.mole;
        } else if (meta.correct === true && meta.accused) {
          world.inferredMole = meta.accused;
        }
      }
      if (meta.mole_name && !world.inferredMoleName) {
        world.inferredMoleName = meta.mole_name;
      }
      if (meta.mole_dept && !world.inferredMoleDept) {
        world.inferredMoleDept = meta.mole_dept;
      }
    }

    if (world.inferredMole && world.employees.length) {
      const emp = world.employees.find((e) => e.id === world.inferredMole);
      if (emp) {
        if (!world.inferredMoleName) world.inferredMoleName = emp.name || "";
        if (!world.inferredMoleDept) world.inferredMoleDept = emp.dept || emp.department || "";
      }
    }

    for (const tName of trackNames) {
      const meta = world.tracks[tName].cachedPostEnd;
      if (meta) {
        if (!meta.mole && world.inferredMole) meta.mole = world.inferredMole;
        if (!meta.mole_name && world.inferredMoleName) meta.mole_name = world.inferredMoleName;
        if (!meta.mole_dept && world.inferredMoleDept) meta.mole_dept = world.inferredMoleDept;
      }
    }
  }

  _getSolverPostEndSummary(world, gemMeta) {
    if (!world) return null;
    if (world.tracks.solver) {
      this._resolvePostEndForWorld(world);
      const sMeta = world.tracks.solver.cachedPostEnd;
      if (sMeta) {
        return {
          sealed: false,
          score: sMeta.score,
          score_fmt: fmtScore(sMeta.score),
          accused: sMeta.accused,
          mole: sMeta.mole,
          correct: Boolean(sMeta.correct),
          end_reason: sMeta.end_reason,
          final_day: sMeta.final_day,
          tool_calls: sMeta.tool_calls,
        };
      }
    }
    if (gemMeta && gemMeta.nestedSolver && typeof gemMeta.nestedSolver === "object") {
      const ns = gemMeta.nestedSolver;
      const sc = toFiniteNumber(ns.score, 0);
      return {
        sealed: false,
        score: sc,
        score_fmt: fmtScore(sc),
        accused: ns.accused ?? null,
        mole: ns.mole ?? gemMeta.mole ?? null,
        correct: Boolean(ns.correct),
        end_reason: String(ns.end_reason || (ns.accused ? "accused" : "horizon")),
        final_day: Math.max(1, Math.trunc(toFiniteNumber(ns.final_day, 1))),
        tool_calls: Math.max(0, Math.trunc(toFiniteNumber(ns.tool_calls, 0))),
      };
    }
    return null;
  }

  _getTrackTerminalDayPreEndSafe(track) {
    if (!track) return null;
    const rawEp = track.rawEp || {};
    const isDualEp = Boolean(Array.isArray(rawEp.steps) && Array.isArray(rawEp.solver_steps));
    const directFinalDay =
      track.canonicalAgent === "solver"
        ? isDualEp
          ? rawEp.solver_final_day
          : rawEp.solver_final_day ?? rawEp.final_day ?? rawEp.finalDay
        : rawEp.final_day ?? rawEp.finalDay;
    if (isFiniteNumber(directFinalDay) && Number(directFinalDay) >= 1) {
      return Math.trunc(Number(directFinalDay));
    }
    const accuseStep = track.steps.find((s) => s.tool === "accuse");
    if (accuseStep) return accuseStep.day;
    const meta = extractPostEndMetaFromRaw(
      track.rawEp,
      track.canonicalAgent,
      track.steps,
      track.sourcePack || this._sourcePack,
      track.tier,
      track.seed
    );
    return meta ? meta.final_day : null;
  }

  loadReplays(dataOrUrl, opts = {}) {
    this._explicitPackProvided = true;
    const mergedOpts = Object.assign({}, this._opts, opts || {});
    if (typeof dataOrUrl === "string") {
      const trimmed = dataOrUrl.trim();
      if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
        this._ingestSource(trimmed, mergedOpts);
        return this;
      }
      const g = getGlobalRoot();
      if (/^https?:/i.test(trimmed) && typeof g.fetch === "function") {
        return g
          .fetch(trimmed)
          .then((res) => res.text())
          .then((txt) => {
            this._ingestSource(txt, mergedOpts);
            return this;
          });
      }
      if (typeof g.process !== "undefined" && g.process && g.process.versions && g.process.versions.node) {
        return import("node:fs/promises")
          .then((fsMod) => fsMod.readFile(trimmed, "utf8"))
          .then((txt) => {
            this._ingestSource(txt, mergedOpts);
            return this;
          });
      }
      if (typeof g.fetch === "function") {
        return g
          .fetch(trimmed)
          .then((res) => res.text())
          .then((txt) => {
            this._ingestSource(txt, mergedOpts);
            return this;
          });
      }
      return Promise.resolve(this);
    }
    this._ingestSource(dataOrUrl, mergedOpts);
    return this;
  }

  listSeeds(tier = "hard") {
    this._syncAutoGlobalPack();
    const normTier = normalizeTier(tier);
    const available = new Set();
    for (const w of this._worlds.values()) {
      if (w.tier === normTier) available.add(w.seed);
    }
    const ordered = [];
    const preferred = this._defaultSeedsByTier.get(normTier);
    if (Array.isArray(preferred)) {
      for (const s of preferred) {
        if (available.has(s) && !ordered.includes(s)) {
          ordered.push(s);
        }
      }
    }
    const rest = Array.from(available)
      .filter((s) => !ordered.includes(s))
      .sort((a, b) => a - b);
    return ordered.concat(rest);
  }

  selectEpisode(tierOrKey, maybeSeed) {
    this._syncAutoGlobalPack();
    let normTier = "hard";
    let normSeed = null;

    if (maybeSeed === undefined) {
      if (typeof tierOrKey === "number") {
        normTier = this._selectedTier || "hard";
        normSeed = Math.trunc(tierOrKey);
      } else if (typeof tierOrKey === "string") {
        const parsed = parseEpisodeKeyString(tierOrKey, this._selectedTier || "hard");
        if (parsed) {
          normTier = parsed.tier;
          normSeed = parsed.seed;
        }
      } else if (tierOrKey && typeof tierOrKey === "object") {
        normTier = normalizeTier(tierOrKey.tier || "hard");
        if (Number.isFinite(Number(tierOrKey.seed))) {
          normSeed = Math.trunc(Number(tierOrKey.seed));
        }
      }
    } else if (typeof tierOrKey === "number" && typeof maybeSeed === "string") {
      normSeed = Math.trunc(tierOrKey);
      normTier = normalizeTier(maybeSeed);
    } else {
      normTier = normalizeTier(tierOrKey);
      normSeed = Math.trunc(Number(maybeSeed));
    }

    if (!Number.isFinite(normSeed)) return null;

    this._selectedTier = normTier;
    this._selectedSeed = normSeed;
    this._currentDay = 1;
    this._humanDone = false;

    const world = this._worlds.get(`${normTier}:${normSeed}`);
    if (!world) return null;

    return {
      key: world.key,
      tier: world.tier,
      seed: world.seed,
      maxDays: world.maxDays,
      n_days: world.maxDays,
      employees: clonePlain(world.employees),
      tracks: Object.keys(world.tracks),
      hasGemini: Boolean(world.tracks.gemini),
      hasSolver: Boolean(world.tracks.solver),
      gemini: world.tracks.gemini
        ? { agent: world.tracks.gemini.agentLabel, available: true }
        : null,
      solver: world.tracks.solver
        ? { agent: world.tracks.solver.agentLabel, available: true }
        : null,
    };
  }

  _parseViewArgs(seedOrOpts, humanDay, humanDone, tier, agent) {
    if (seedOrOpts && typeof seedOrOpts === "object") {
      const o = seedOrOpts;
      let resolvedTier = normalizeTier(o.tier || "hard");
      let resolvedSeed = o.seed;
      let resolvedAgent = o.agent || "gemini";
      if (typeof o.key === "string") {
        const pk = parseEpisodeKeyString(o.key, resolvedTier);
        if (pk) {
          resolvedTier = pk.tier;
          resolvedSeed = pk.seed;
          if (pk.agent && !o.agent) resolvedAgent = pk.agent;
        }
      }
      const d = o.humanDay ?? o.human_day ?? o.day ?? 1;
      const doneFlag = Boolean(o.humanDone ?? o.human_done ?? o.done ?? false);
      const maxCallRaw = o.maxCallIdx ?? o.max_call_idx ?? null;
      const maxCallIdx =
        maxCallRaw !== null && maxCallRaw !== undefined && Number.isFinite(Number(maxCallRaw))
          ? Math.trunc(Number(maxCallRaw))
          : null;
      return {
        tier: resolvedTier,
        seed: Number.isFinite(Number(resolvedSeed))
          ? Math.trunc(Number(resolvedSeed))
          : this._selectedSeed,
        humanDay: Math.max(1, Math.trunc(toFiniteNumber(d, 1))),
        humanDone: doneFlag,
        agent: resolvedAgent,
        maxCallIdx,
      };
    }

    if (typeof seedOrOpts === "string") {
      const trimmed = seedOrOpts.trim();
      if (KNOWN_TIERS.has(trimmed.toLowerCase()) && humanDay !== undefined && Number.isFinite(Number(humanDay))) {
        const parsedSeed = Math.trunc(Number(humanDay));
        const parsedDay = Math.max(1, Math.trunc(toFiniteNumber(humanDone, 1)));
        const parsedDone = Boolean(tier);
        const parsedAgent = agent || "gemini";
        return {
          tier: normalizeTier(trimmed),
          seed: parsedSeed,
          humanDay: parsedDay,
          humanDone: parsedDone,
          agent: parsedAgent,
          maxCallIdx: null,
        };
      }
      const pk = parseEpisodeKeyString(trimmed, tier || "hard");
      if (pk) {
        const extraOpts =
          tier && typeof tier === "object"
            ? tier
            : agent && typeof agent === "object"
              ? agent
              : null;
        const maxCallRaw = extraOpts ? extraOpts.maxCallIdx ?? extraOpts.max_call_idx : null;
        return {
          tier: pk.tier,
          seed: pk.seed,
          humanDay: Math.max(1, Math.trunc(toFiniteNumber(humanDay, 1))),
          humanDone: Boolean(humanDone),
          agent:
            pk.agent ||
            (typeof tier === "string" && !KNOWN_TIERS.has(tier.toLowerCase()) ? tier : null) ||
            (typeof agent === "string" ? agent : null) ||
            "gemini",
          maxCallIdx:
            maxCallRaw !== null && maxCallRaw !== undefined && Number.isFinite(Number(maxCallRaw))
              ? Math.trunc(Number(maxCallRaw))
              : null,
        };
      }
    }

    let extraOpts = null;
    let resolvedTier = "hard";
    let resolvedAgent = "gemini";

    if (tier && typeof tier === "object") {
      extraOpts = tier;
      resolvedTier = normalizeTier(tier.tier || "hard");
      resolvedAgent = tier.agent || (typeof agent === "string" ? agent : "gemini");
    } else {
      resolvedTier = normalizeTier(tier || "hard");
      if (agent && typeof agent === "object") {
        extraOpts = agent;
        resolvedAgent = agent.agent || "gemini";
      } else if (typeof agent === "string" && agent.trim()) {
        resolvedAgent = agent.trim();
      }
    }

    const maxCallRaw = extraOpts ? extraOpts.maxCallIdx ?? extraOpts.max_call_idx : null;
    const maxCallIdx =
      maxCallRaw !== null && maxCallRaw !== undefined && Number.isFinite(Number(maxCallRaw))
        ? Math.trunc(Number(maxCallRaw))
        : null;

    return {
      tier: resolvedTier,
      seed: Number.isFinite(Number(seedOrOpts))
        ? Math.trunc(Number(seedOrOpts))
        : this._selectedSeed,
      humanDay: Math.max(1, Math.trunc(toFiniteNumber(humanDay, 1))),
      humanDone: Boolean(humanDone),
      agent: resolvedAgent,
      maxCallIdx,
    };
  }

  getDuelView(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
    this._syncAutoGlobalPack();
    const q = this._parseViewArgs(seedOrOpts, humanDay, humanDone, tier, agent);
    const canonicalAgent = canonicalizeAgent(q.agent);
    const defaults = TIER_DEFAULTS[q.tier] || TIER_DEFAULTS.hard;

    if (q.humanDone === true) {
      this._humanDone = true;
    }

    const world =
      q.seed !== null && q.seed !== undefined
        ? this._worlds.get(`${q.tier}:${q.seed}`)
        : null;
    const track =
      (world && (world.tracks[canonicalAgent] || world.tracks[q.agent])) ||
      (q.seed !== null && q.seed !== undefined
        ? this._trackMap.get(`${q.tier}:${q.seed}:${canonicalAgent}`) ||
          this._trackMap.get(`${q.tier}:${q.seed}:${q.agent}`)
        : null);

    if (!world || !track) {
      return {
        available: false,
        seed: q.seed,
        tier: q.tier,
        agent: defaultAgentLabel(canonicalAgent, q.agent),
        agent_key: canonicalAgent,
        day: q.humanDay,
        human_day: q.humanDay,
        human_done: q.humanDone,
        done: q.humanDone,
        max_days: world ? world.maxDays : defaults.n_days,
        n_days: world ? world.maxDays : defaults.n_days,
        V: 1.0,
        known_v: 1.0,
        visible_v: 1.0,
        steps: [],
        status: "unavailable",
        sealed_day: null,
        final: null,
      };
    }

    if (q.humanDone === true) {
      this._resolvePostEndForWorld(world);
      const meta = track.cachedPostEnd;
      const unlockedSteps = track.steps.map((s) => {
        const isAcc = s.tool === "accuse";
        const resolvedAccused = isAcc ? s.unsealedAccused || meta.accused || null : null;
        const stepArgs = isAcc
          ? resolvedAccused
            ? { employee: resolvedAccused }
            : {}
          : clonePlain(s.rawArgs);
        const stepSummary = isAcc
          ? resolvedAccused
            ? `Accused ${resolvedAccused}`
            : s.unsealedSummary
          : s.unsealedSummary;
        const stepObj = {
          day: s.day,
          call_idx: s.call_idx,
          t: s.t,
          tool: s.tool,
          args: stepArgs,
          ok: s.ok,
          summary: stepSummary,
          V: s.known_v,
          known_v: s.known_v,
          visible_v: s.known_v,
          sealed: false,
        };
        if (s.commentary) stepObj.commentary = s.commentary;
        return stepObj;
      });

      const lastKnownV = unlockedSteps.length
        ? unlockedSteps[unlockedSteps.length - 1].known_v
        : 1.0;
      const counts = summarizePublicStepCounts(unlockedSteps);

      const solverSummary =
        canonicalAgent === "gemini" ? this._getSolverPostEndSummary(world, meta) : null;

      const finalPayload = {
        sealed: false,
        score: meta.score,
        score_fmt: fmtScore(meta.score),
        accused: meta.accused ?? null,
        mole: meta.mole ?? null,
        mole_name: meta.mole_name || "",
        mole_dept: meta.mole_dept || "",
        correct: Boolean(meta.correct),
        end_reason: meta.end_reason,
        final_day: meta.final_day,
        tool_calls: meta.tool_calls,
      };
      if (solverSummary) {
        finalPayload.solver = solverSummary;
      }

      return {
        available: true,
        seed: world.seed,
        tier: world.tier,
        agent: track.agentLabel,
        agent_key: track.canonicalAgent,
        day: meta.final_day,
        human_day: q.humanDay,
        human_done: true,
        done: true,
        max_days: world.maxDays,
        n_days: world.maxDays,
        V: lastKnownV,
        known_v: lastKnownV,
        visible_v: lastKnownV,
        visible_V: lastKnownV,
        canaries_planted: counts.canaries_planted,
        interviews_done: counts.interviews_done,
        restricted_count: counts.restricted_count,
        tool_calls_so_far: counts.tool_calls_so_far,
        steps: unlockedSteps,
        status: "finished",
        sealed_day: null,
        final: finalPayload,
      };
    }

    const gatedSteps = [];
    let accuseDayInWindow = null;

    for (const s of track.steps) {
      if (s.day > q.humanDay) continue;
      if (q.maxCallIdx !== null && s.call_idx > q.maxCallIdx) continue;
      const isAcc = s.tool === "accuse";
      if (isAcc && (accuseDayInWindow === null || s.day < accuseDayInWindow)) {
        accuseDayInWindow = s.day;
      }
      const stepObj = {
        day: s.day,
        call_idx: s.call_idx,
        t: s.t,
        tool: s.tool,
        args: isAcc ? { employee: "[SEALED]" } : scrubPreEndObject(s.rawArgs),
        ok: s.ok,
        summary: isAcc ? "Accusation filed [SEALED]" : s.unsealedSummary,
        V: s.known_v,
        known_v: s.known_v,
        visible_v: s.known_v,
        sealed: isAcc,
      };
      if (!isAcc && s.commentary) stepObj.commentary = s.commentary;
      gatedSteps.push(stepObj);
    }

    const currentKnownV = gatedSteps.length
      ? gatedSteps[gatedSteps.length - 1].known_v
      : 1.0;
    const preCounts = summarizePublicStepCounts(gatedSteps);

    const terminalDay = this._getTrackTerminalDayPreEndSafe(track);
    const lastTrackCallIdx = track.steps.length
      ? track.steps[track.steps.length - 1].call_idx
      : -1;
    const callCapReachedAll =
      q.maxCallIdx === null || q.maxCallIdx >= lastTrackCallIdx;

    const isSealedEnd =
      accuseDayInWindow !== null ||
      (callCapReachedAll && terminalDay !== null && terminalDay <= q.humanDay);

    const sealedDay =
      accuseDayInWindow !== null
        ? accuseDayInWindow
        : isSealedEnd
          ? terminalDay
          : null;

    return {
      available: true,
      seed: world.seed,
      tier: world.tier,
      agent: track.agentLabel,
      agent_key: track.canonicalAgent,
      day: q.humanDay,
      human_day: q.humanDay,
      human_done: false,
      done: false,
      max_days: world.maxDays,
      n_days: world.maxDays,
      V: currentKnownV,
      known_v: currentKnownV,
      visible_v: currentKnownV,
      visible_V: currentKnownV,
      canaries_planted: preCounts.canaries_planted,
      interviews_done: preCounts.interviews_done,
      restricted_count: preCounts.restricted_count,
      tool_calls_so_far: preCounts.tool_calls_so_far,
      steps: gatedSteps,
      status: isSealedEnd ? "sealed_accusation" : "in_progress",
      sealed_day: sealedDay,
      final: isSealedEnd ? { sealed: true, final_day: sealedDay } : null,
    };
  }

  getDayState(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
    return this.getDuelView(seedOrOpts, humanDay, humanDone, tier, agent);
  }

  getView(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
    return this.getDuelView(seedOrOpts, humanDay, humanDone, tier, agent);
  }

  getEpisodeView(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
    return this.getDuelView(seedOrOpts, humanDay, humanDone, tier, agent);
  }

  _ensureSelectedWorld() {
    this._syncAutoGlobalPack();
    if (this._selectedSeed === null) {
      const hardSeeds = this.listSeeds("hard");
      if (hardSeeds.length) {
        this._selectedTier = "hard";
        this._selectedSeed = hardSeeds[0];
      } else {
        const firstWorld = this._worlds.values().next().value;
        if (firstWorld) {
          this._selectedTier = firstWorld.tier;
          this._selectedSeed = firstWorld.seed;
        }
      }
    }
    if (this._selectedSeed === null) return null;
    return this._worlds.get(`${this._selectedTier}:${this._selectedSeed}`) || null;
  }

  getOpponentState(agentKey = "gemini", humanDay = 1, humanDone = false, opts = {}) {
    this._syncAutoGlobalPack();
    const extra = opts && typeof opts === "object" ? opts : {};
    if (extra.tier !== undefined && extra.seed !== undefined) {
      this._selectedTier = normalizeTier(extra.tier);
      this._selectedSeed = Math.trunc(Number(extra.seed));
    } else {
      this._ensureSelectedWorld();
    }

    const dayCap = Math.max(1, Math.trunc(toFiniteNumber(humanDay, this._currentDay || 1)));
    const doneFlag = Boolean(humanDone);
    this._currentDay = dayCap;
    this._humanDone = doneFlag;

    const view = this.getDuelView({
      tier: this._selectedTier,
      seed: this._selectedSeed,
      humanDay: dayCap,
      humanDone: doneFlag,
      agent: agentKey,
      maxCallIdx: extra.maxCallIdx ?? extra.max_call_idx ?? null,
    });

    if (!view.available) {
      return {
        available: false,
        tier: view.tier,
        seed: view.seed,
        agent: view.agent,
        agentKey: view.agent_key,
        day: dayCap,
        humanDay: dayCap,
        humanDone: doneFlag,
        status: "unavailable",
        sealedDay: null,
        sealed_day: null,
        accused: null,
        correct: null,
        score: null,
        known_v: 1.0,
        visible_v: 1.0,
        V: 1.0,
        tool_calls_so_far: 0,
        steps: [],
        final: null,
      };
    }

    if (doneFlag) {
      const fin = view.final;
      return {
        available: true,
        tier: view.tier,
        seed: view.seed,
        agent: view.agent,
        agentKey: view.agent_key,
        day: fin.final_day,
        humanDay: dayCap,
        humanDone: true,
        status: "finished",
        sealedDay: null,
        sealed_day: null,
        accused: fin.accused,
        correct: fin.correct,
        final_day: fin.final_day,
        tool_calls: fin.tool_calls,
        score: fin.score,
        score_fmt: fin.score_fmt,
        end_reason: fin.end_reason,
        mole: fin.mole,
        mole_name: fin.mole_name,
        mole_dept: fin.mole_dept,
        known_v: view.known_v,
        visible_v: view.visible_v,
        V: view.V,
        steps: view.steps,
        final: fin,
      };
    }

    const isSealed = view.status === "sealed_accusation";
    return {
      available: true,
      tier: view.tier,
      seed: view.seed,
      agent: view.agent,
      agentKey: view.agent_key,
      day: isSealed && view.sealed_day !== null ? Math.min(dayCap, view.sealed_day) : dayCap,
      humanDay: dayCap,
      humanDone: false,
      status: isSealed ? "sealed_accusation" : "investigating",
      sealedDay: view.sealed_day,
      sealed_day: view.sealed_day,
      accused: isSealed ? "[SEALED]" : null,
      correct: null,
      score: null,
      known_v: view.known_v,
      visible_v: view.visible_v,
      V: view.V,
      tool_calls_so_far: view.steps.length,
      steps: view.steps,
      final: view.final,
    };
  }

  stepToDay(humanDay = 1, humanDone = false) {
    const world = this._ensureSelectedWorld();
    const dayCap = Math.max(1, Math.trunc(toFiniteNumber(humanDay, 1)));
    const doneFlag = Boolean(humanDone);
    this._currentDay = dayCap;
    this._humanDone = doneFlag;

    return {
      tier: this._selectedTier,
      seed: this._selectedSeed,
      day: dayCap,
      humanDay: dayCap,
      humanDone: doneFlag,
      maxDays: world ? world.maxDays : (TIER_DEFAULTS[this._selectedTier] || TIER_DEFAULTS.hard).n_days,
      gemini: this.getOpponentState("gemini", dayCap, doneFlag),
      solver: this.getOpponentState("solver", dayCap, doneFlag),
    };
  }

  compareWithHuman(humanResult, humanDoneOverride = undefined) {
    let isDone = false;
    if (humanDoneOverride !== undefined) {
      isDone = Boolean(humanDoneOverride);
    } else if (humanResult && typeof humanResult === "object") {
      if (humanResult.humanDone !== undefined) {
        isDone = Boolean(humanResult.humanDone);
      } else if (humanResult.human_done !== undefined) {
        isDone = Boolean(humanResult.human_done);
      } else if (humanResult.done !== undefined) {
        isDone = Boolean(humanResult.done);
      } else {
        isDone = Boolean(this._humanDone);
      }
    } else {
      isDone = Boolean(this._humanDone);
    }

    if (!isDone) return null;

    if (humanResult && typeof humanResult === "object") {
      if (humanResult.tier !== undefined && humanResult.seed !== undefined) {
        this._selectedTier = normalizeTier(humanResult.tier);
        this._selectedSeed = Math.trunc(Number(humanResult.seed));
      } else if (humanResult.seed !== undefined && Number.isFinite(Number(humanResult.seed))) {
        this._selectedSeed = Math.trunc(Number(humanResult.seed));
      }
    }

    const world = this._ensureSelectedWorld();
    if (world) {
      this._resolvePostEndForWorld(world);
    }

    const rawHuman =
      humanResult && humanResult.you && typeof humanResult.you === "object"
        ? humanResult.you
        : humanResult && typeof humanResult === "object"
          ? humanResult
          : {};

    const moleId =
      (humanResult && typeof humanResult.mole === "string" && humanResult.mole) ||
      (world && world.inferredMole) ||
      null;

    const humanScore = toFiniteNumber(rawHuman.score, 0);
    const humanAccused =
      rawHuman.accused !== undefined && rawHuman.accused !== ""
        ? rawHuman.accused
        : null;
    const humanCorrect =
      typeof rawHuman.correct === "boolean"
        ? rawHuman.correct
        : Boolean(moleId && humanAccused && humanAccused === moleId);
    const humanFinalDay = Math.max(
      1,
      Math.trunc(toFiniteNumber(rawHuman.final_day ?? rawHuman.finalDay ?? rawHuman.day, this._currentDay || 1))
    );
    const humanCalls = Math.max(
      0,
      Math.trunc(toFiniteNumber(rawHuman.tool_calls ?? rawHuman.toolCalls ?? rawHuman.calls, 0))
    );
    const humanEndReason = String(
      rawHuman.end_reason || rawHuman.endReason || (humanAccused ? "accused" : "horizon")
    );

    const humanRec = {
      available: true,
      score: humanScore,
      score_fmt: fmtScore(humanScore),
      formattedScore: fmtScore(humanScore),
      accused: humanAccused,
      correct: humanCorrect,
      final_day: humanFinalDay,
      tool_calls: humanCalls,
      end_reason: humanEndReason,
    };

    const gemState = this.getOpponentState("gemini", humanFinalDay, true);
    const geminiRec = gemState.available
      ? {
          available: true,
          score: gemState.score,
          score_fmt: fmtScore(gemState.score),
          formattedScore: fmtScore(gemState.score),
          accused: gemState.accused,
          correct: gemState.correct,
          final_day: gemState.final_day,
          tool_calls: gemState.tool_calls,
          end_reason: gemState.end_reason,
        }
      : null;

    let solverRec = null;
    const solState = this.getOpponentState("solver", humanFinalDay, true);
    if (solState.available) {
      solverRec = {
        available: true,
        score: solState.score,
        score_fmt: fmtScore(solState.score),
        formattedScore: fmtScore(solState.score),
        accused: solState.accused,
        correct: solState.correct,
        final_day: solState.final_day,
        tool_calls: solState.tool_calls,
        end_reason: solState.end_reason,
      };
    } else if (gemState.available && gemState.final && gemState.final.solver) {
      const sf = gemState.final.solver;
      solverRec = {
        available: true,
        score: sf.score,
        score_fmt: fmtScore(sf.score),
        formattedScore: fmtScore(sf.score),
        accused: sf.accused,
        correct: sf.correct,
        final_day: sf.final_day,
        tool_calls: sf.tool_calls,
        end_reason: sf.end_reason,
      };
    } else if (humanResult && humanResult.solver && typeof humanResult.solver === "object") {
      const hs = humanResult.solver;
      const sc = toFiniteNumber(hs.score, 0);
      solverRec = {
        available: true,
        score: sc,
        score_fmt: fmtScore(sc),
        formattedScore: fmtScore(sc),
        accused: hs.accused ?? null,
        correct: Boolean(hs.correct),
        final_day: Math.max(1, Math.trunc(toFiniteNumber(hs.final_day, 1))),
        tool_calls: Math.max(0, Math.trunc(toFiniteNumber(hs.tool_calls, 0))),
        end_reason: String(hs.end_reason || (hs.accused ? "accused" : "horizon")),
      };
    }

    const firstCatch = computeFirstCatchFromContenders(humanRec, solverRec, geminiRec);
    const { winner, winnerLabel } = computeWinnerFromContenders(humanRec, geminiRec, solverRec);

    const clauses = [
      formatActorClause("You", humanRec, false),
      geminiRec ? formatActorClause("Gemini", geminiRec, true) : null,
      solverRec ? formatActorClause("Solver", solverRec, false) : null,
    ].filter(Boolean);

    const tierLabel = this._selectedTier || "hard";
    const seedLabel = this._selectedSeed !== null ? this._selectedSeed : "?";
    const summary = `CANARY ARENA | Seed ${seedLabel} (${tierLabel}) | ${clauses.join(" vs ")} | First catch: ${firstCatch}`;

    return {
      tier: tierLabel,
      seed: this._selectedSeed,
      mole: moleId,
      mole_name: world ? world.inferredMoleName : "",
      mole_dept: world ? world.inferredMoleDept : "",
      human: humanRec,
      you: humanRec,
      gemini: geminiRec,
      solver: solverRec,
      winner,
      winnerLabel,
      firstCatch,
      first_catch: firstCatch,
      summary,
    };
  }

  static createReplayEngine(pack, opts) {
    return new CanaryReplayEngine(pack, opts);
  }

  static fromPack(pack, opts) {
    return new CanaryReplayEngine(pack, opts);
  }

  static fromJsonl(jsonlText, opts) {
    return new CanaryReplayEngine(jsonlText, opts);
  }

  static _getDefaultEngine() {
    if (!CanaryReplayEngine._defaultInstance) {
      CanaryReplayEngine._defaultInstance = new CanaryReplayEngine();
    } else {
      CanaryReplayEngine._defaultInstance._syncAutoGlobalPack();
    }
    return CanaryReplayEngine._defaultInstance;
  }

  static setDefaultPack(pack, opts) {
    CanaryReplayEngine._defaultInstance = new CanaryReplayEngine(pack, opts);
    return CanaryReplayEngine._defaultInstance;
  }

  static loadReplays(dataOrUrl, opts) {
    const inst = new CanaryReplayEngine(undefined, opts);
    CanaryReplayEngine._defaultInstance = inst;
    return inst.loadReplays(dataOrUrl, opts);
  }

  static listSeeds(tier = "hard") {
    return CanaryReplayEngine._getDefaultEngine().listSeeds(tier);
  }

  static getDuelView(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
    return CanaryReplayEngine._getDefaultEngine().getDuelView(
      seedOrOpts,
      humanDay,
      humanDone,
      tier,
      agent
    );
  }

  static getDayState(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
    return CanaryReplayEngine._getDefaultEngine().getDayState(
      seedOrOpts,
      humanDay,
      humanDone,
      tier,
      agent
    );
  }

  static getView(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
    return CanaryReplayEngine._getDefaultEngine().getView(
      seedOrOpts,
      humanDay,
      humanDone,
      tier,
      agent
    );
  }

  static getEpisodeView(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
    return CanaryReplayEngine._getDefaultEngine().getEpisodeView(
      seedOrOpts,
      humanDay,
      humanDone,
      tier,
      agent
    );
  }
}

CanaryReplayEngine._defaultInstance = null;

export function createReplayEngine(pack, opts) {
  return new CanaryReplayEngine(pack, opts);
}

export function fromPack(pack, opts) {
  return CanaryReplayEngine.fromPack(pack, opts);
}

export function fromJsonl(jsonlText, opts) {
  return CanaryReplayEngine.fromJsonl(jsonlText, opts);
}

export function loadReplays(dataOrUrl, opts) {
  return CanaryReplayEngine.loadReplays(dataOrUrl, opts);
}

export function listSeeds(tier = "hard") {
  return CanaryReplayEngine.listSeeds(tier);
}

export function getDuelView(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
  return CanaryReplayEngine.getDuelView(seedOrOpts, humanDay, humanDone, tier, agent);
}

export function getDayState(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
  return CanaryReplayEngine.getDayState(seedOrOpts, humanDay, humanDone, tier, agent);
}

export function getView(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
  return CanaryReplayEngine.getView(seedOrOpts, humanDay, humanDone, tier, agent);
}

export function getEpisodeView(seedOrOpts, humanDay = 1, humanDone = false, tier = "hard", agent = "gemini") {
  return CanaryReplayEngine.getEpisodeView(seedOrOpts, humanDay, humanDone, tier, agent);
}

export default CanaryReplayEngine;

const globalRootObj = getGlobalRoot();
if (globalRootObj && typeof globalRootObj === "object") {
  globalRootObj.CanaryReplayEngine = CanaryReplayEngine;
}
