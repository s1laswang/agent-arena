import {
  el,
  clear,
  pad2,
  fmtScore,
  setDocument,
  MODE_DEFS,
  TOOL_GROUPS,
  TOOL_DEFS,
  DEFAULT_DUEL_SEEDS,
  OfficeStage,
  mountArenaUI,
  sanitizeStepForPreEnd,
  scrubPreEndObject,
  sanitizeGeminiReplayState,
  sanitizeSolverLiveState,
  computeFirstCatchLabel,
  buildCanonicalShareLine,
} from "./ui/index.js";

export const KENNEY_ASSET_CREDITS =
  "Pixel art & tiles: Kenney Vleugels (Kenney.nl) - CC0 1.0 Public Domain with deterministic procedural fallback.";

export const SPRITE_PACK_MANIFEST_PATH = "./assets/sprite_pack_manifest.json";

export const GEMINI_REPLAYS_JSON_PATH = "./data/gemini_replays.json";

export const PYODIDE_CDN_URL = [
  "https:",
  "",
  "cdn.jsdelivr.net",
  "pyodide",
  "v0.27.7",
  "full",
  "pyodide.js",
].join("/");

export const DEFAULT_LIVING_BANNER =
  "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate (LA 0.452 vs 0.493 control); 100% offline cached gemini-4-carbon chatter, 0 score drift";

export const OPTIONAL_SIBLING_MODULES = [
  ["aiDuelPanel", "./ui/ai_duel_panel.js"],
  ["humanDesk", "./ui/human_desk.js"],
  ["endScreen", "./ui/end_screen.js"],
  ["leaderboard", "./ui/leaderboard.js"],
  ["replayEngine", "./replay_engine.js"],
  ["committedDuelPack", "./data/committed_duel_pack.js"],
  ["moleMode", "./mole_mode.js"],
  ["livingOffice", "./living_office.js"],
  ["livingOfficePack", "./data/living_office_pack.js"],
  ["solverLive", "./solver_live.js"],
  ["tiebreakTraces", "./data/tiebreak_traces.js"],
  ["moleRivals", "./mole_rivals.js"],
  ["shareCard", "./share_card.js"],
  ["transcriptCommentary", "./data/transcript_commentary.js"],
];

const PRE_END_FORBIDDEN_KEYS = new Set([
  "mole",
  "true_mole",
  "mole_id",
  "moleId",
  "decoy",
  "true_decoy",
  "decoy_id",
  "decoyId",
  "correct",
  "accused_correct",
  "true_v",
  "true_V",
  "trueV",
  "world_seed",
  "_world",
  "leaking_sprite_employee",
  "mole_sprite",
  "culprit_sprite",
  "leaker_employee",
  "is_mole",
  "sealed_verdict",
  "verdict",
  "reveal",
]);

const MOLE_DOC_HIDDEN_KEYS = new Set([
  "is_canary",
  "true_v",
  "true_V",
  "trueV",
  "raw_doc_id",
  "raw_title",
  "true_variant",
  "variant_recipients",
]);

const VALID_MODE_IDS = new Set(MODE_DEFS.map((m) => m.id));
const VALID_TIERS = new Set(["easy", "medium", "hard"]);

const PYTHON_BRIDGE_SOURCE = [
  "import importlib",
  "import json",
  "import math",
  "import sys",
  "if '/home/pyodide' not in sys.path:",
  "    sys.path.insert(0, '/home/pyodide')",
  "_arena_mod = None",
  "_canary_mod = None",
  "_mole_mod = None",
  "_solver_cache = {}",
  "def _try_mod(name):",
  "    try:",
  "        return importlib.import_module(name)",
  "    except Exception:",
  "        return None",
  "def refresh_modules():",
  "    global _arena_mod, _canary_mod, _mole_mod",
  "    _arena_mod = _try_mod('arena_game')",
  "    _canary_mod = _try_mod('canary_game')",
  "    _mole_mod = _try_mod('mole_mode')",
  "refresh_modules()",
  "def _validate_seed(seed, mode_name):",
  "    if isinstance(seed, bool) or seed is None:",
  "        raise ValueError('seed must be an integer')",
  "    s = int(seed)",
  "    if str(seed).strip() != str(s):",
  "        raise ValueError('seed must be canonical integer')",
  "    if s < 0 or s > 9999:",
  "        raise ValueError('seed outside allowed public dev range 0..9999')",
  "    if mode_name == 'solver':",
  "        if s < 3000 or s > 9999:",
  "            raise ValueError('solver seed must be in 3000..9999')",
  "    elif mode_name == 'mole':",
  "        if not (s in (6, 26) or 3000 <= s <= 9999):",
  "            raise ValueError('mole seed must be 6, 26, or 3000..9999')",
  "    else:",
  "        if not (0 <= s <= 29 or 3000 <= s <= 9999):",
  "            raise ValueError('duel or living seed must be 0..29 or 3000..9999')",
  "    return s",
  "def _compute_solver_trace(tier_name, seed_num):",
  "    key = (tier_name, seed_num)",
  "    if key in _solver_cache:",
  "        return _solver_cache[key]",
  "    from canary.env import Env",
  "    from canary.solver.policy import SolverPolicy",
  "    sol_env = Env(tier_name, seed_num)",
  "    pol = SolverPolicy()",
  "    pol.reset(sol_env.tools_spec(), sol_env.instruction())",
  "    by_day = {}",
  "    canaries = 0",
  "    interviews = 0",
  "    calls = 0",
  "    def _snap(day_idx):",
  "        top_p = 1.0 / max(1, len(sol_env._world.employees))",
  "        ent = math.log2(max(1, len(sol_env._world.employees)))",
  "        if getattr(pol, 'trace', None):",
  "            post = pol.trace[-1].get('post') or {}",
  "            probs = [float(v) for v in post.values() if float(v) > 0.0]",
  "            if probs:",
  "                top_p = max(probs)",
  "                ent = -sum(p * math.log2(p) for p in probs)",
  "        by_day[day_idx] = {",
  "            'day': day_idx,",
  "            'visible_V': sol_env.visible_V(),",
  "            'canaries_planted': canaries,",
  "            'interviews_done': interviews,",
  "            'restricted_count': len(sol_env._restricted),",
  "            'tool_calls_so_far': calls,",
  "            'top_posterior_prob': round(top_p, 4),",
  "            'entropy_bits': round(max(0.0, ent), 4),",
  "        }",
  "    _snap(1)",
  "    while not sol_env.done:",
  "        t_name, t_args = pol.act(sol_env.history)",
  "        res = sol_env.call(t_name, t_args)",
  "        calls += 1",
  "        if res.ok and t_name == 'plant_canary':",
  "            canaries += 1",
  "        elif res.ok and t_name == 'interview':",
  "            interviews += 1",
  "        _snap(sol_env.day)",
  "    sv = sol_env.verdict()",
  "    out = {",
  "        'by_day': by_day,",
  "        'max_day': max(by_day.keys()) if by_day else 1,",
  "        'final': {",
  "            'score': sv['score'],",
  "            'accused': sv['accused'],",
  "            'correct': sv['correct'],",
  "            'final_day': sv['final_day'],",
  "            'tool_calls': len(sol_env.history),",
  "        },",
  "    }",
  "    _solver_cache[key] = out",
  "    return out",
  "def solver_day_state_json(tier_name, seed, human_day, human_done):",
  "    t = str(tier_name or 'hard').strip()",
  "    if t not in ('easy', 'medium', 'hard'):",
  "        raise ValueError('invalid tier')",
  "    s = _validate_seed(seed, 'duel')",
  "    d = max(1, int(human_day or 1))",
  "    done_flag = bool(human_done)",
  "    if _arena_mod is not None and hasattr(_arena_mod, 'solver_day_state_json'):",
  "        return _arena_mod.solver_day_state_json(t, s, d, done_flag)",
  "    tr = _compute_solver_trace(t, s)",
  "    clamped = min(d, tr['max_day'])",
  "    snap = dict(tr['by_day'].get(clamped) or tr['by_day'][tr['max_day']])",
  "    fin = tr['final']",
  "    if done_flag:",
  "        snap['status'] = 'unlocked'",
  "        snap['sealed_day'] = None",
  "        snap['final'] = dict(fin)",
  "    else:",
  "        early = bool(fin.get('accused') and int(fin.get('final_day', 999)) <= d)",
  "        snap['status'] = 'sealed_accusation' if early else 'hunting'",
  "        snap['sealed_day'] = int(fin['final_day']) if early else None",
  "        snap['final'] = None",
  "    return json.dumps(snap)",
  "def make_investigator_case(mode_name, tier_name, seed):",
  "    m = str(mode_name or 'duel').strip()",
  "    t = str(tier_name or ('medium' if m == 'solver' else 'hard')).strip()",
  "    if t not in ('easy', 'medium', 'hard'):",
  "        raise ValueError('invalid tier')",
  "    s = _validate_seed(seed, m)",
  "    if _arena_mod is not None:",
  "        for attr in ('ArenaGame', 'Game', 'start_case', 'create_game'):",
  "            fn = getattr(_arena_mod, attr, None)",
  "            if callable(fn):",
  "                for call_args in ((t, s, m), (t, s), (s, t), (s,)):",
  "                    try:",
  "                        return fn(*call_args)",
  "                    except TypeError:",
  "                        continue",
  "    if _canary_mod is not None and t == 'medium' and 3000 <= s <= 9999:",
  "        return _canary_mod.Game(s)",
  "    from canary.env import Env",
  "    from canary.rules import TIERS_VERSION",
  "    env_box = Env(t, s)",
  "    act_log = []",
  "    class _IsolatedInvestigatorCase:",
  "        def spec_json(self):",
  "            return json.dumps({",
  "                'mode': m,",
  "                'tier': t,",
  "                'seed': s,",
  "                'tiers_version': TIERS_VERSION,",
  "                'tools': env_box.tools_spec(),",
  "                'instruction': env_box.instruction(),",
  "            })",
  "        def call_json(self, tool_name, args_json):",
  "            try:",
  "                parsed_args = json.loads(args_json) if args_json else {}",
  "            except ValueError:",
  "                return json.dumps({'ok': False, 'data': {}, 'error': 'arguments are not valid JSON', 'done': env_box.done})",
  "            res = env_box.call(tool_name, parsed_args)",
  "            act_log.append([tool_name, parsed_args])",
  "            return json.dumps({'ok': res.ok, 'data': res.data, 'error': res.error, 'done': env_box.done}, default=str)",
  "        def reveal_json(self):",
  "            if not env_box.done:",
  "                return json.dumps({'error': 'the episode is not over yet'})",
  "            verdict = env_box.verdict()",
  "            sv = _compute_solver_trace(t, s)['final']",
  "            return json.dumps({",
  "                'seed': s,",
  "                'tier': t,",
  "                'tiers_version': TIERS_VERSION,",
  "                'you': {",
  "                    'score': verdict['score'],",
  "                    'end_reason': verdict['end_reason'],",
  "                    'accused': verdict['accused'],",
  "                    'correct': verdict['correct'],",
  "                    'final_day': verdict['final_day'],",
  "                    'tool_calls': len(act_log),",
  "                },",
  "                'mole': env_box._world.mole,",
  "                'solver': dict(sv),",
  "            })",
  "        def actions_json(self):",
  "            return json.dumps({'tier': t, 'seed': s, 'tiers_version': TIERS_VERSION, 'actions': act_log})",
  "    return _IsolatedInvestigatorCase()",
  "def make_mole_case(tier_name, seed):",
  "    t = str(tier_name or 'medium').strip()",
  "    if t not in ('medium', 'hard'):",
  "        raise ValueError('mole tier must be medium or hard')",
  "    s = _validate_seed(seed, 'mole')",
  "    if _mole_mod is None:",
  "        raise RuntimeError('mole_mode Python module is not loaded')",
  "    cls = getattr(_mole_mod, 'MoleModeSession', None) or getattr(_mole_mod, 'start_mole_game', None)",
  "    if not callable(cls):",
  "        raise RuntimeError('MoleModeSession entrypoint missing')",
  "    try:",
  "        raw_sess = cls(seed=s, tier=t)",
  "    except ValueError:",
  "        if s in (6, 26):",
  "            raw_sess = cls(seed=3000 + s, tier=t)",
  "        else:",
  "            raise",
  "    if hasattr(raw_sess, 'day_view_json') and hasattr(raw_sess, 'step_json'):",
  "        return raw_sess",
  "    class _MoleJsonHandle:",
  "        def day_view_json(self):",
  "            return json.dumps(raw_sess.get_mole_day_view(), default=str)",
  "        def step_json(self, action_json):",
  "            return json.dumps(raw_sess.step_mole_day(action_json), default=str)",
  "        def debrief_json(self):",
  "            return json.dumps(raw_sess.get_mole_debrief(), default=str)",
  "    return _MoleJsonHandle()",
].join("\n");

function getGlobal() {
  if (typeof globalThis !== "undefined") return globalThis;
  if (typeof window !== "undefined") return window;
  return {};
}

export function validateArenaSeed(seed, mode = "duel") {
  if (typeof seed === "boolean" || seed === null || seed === undefined) {
    throw new RangeError("Seed must be an integer in allowed public dev range");
  }
  const str = String(seed).trim();
  if (!/^\d+$/.test(str)) {
    throw new RangeError("Seed must be a canonical non-negative integer");
  }
  const num = Number(str);
  if (!Number.isSafeInteger(num) || String(num) !== str) {
    throw new RangeError("Seed must be a safe integer");
  }
  if (num < 0 || num > 9999) {
    throw new RangeError("Seed outside allowed public dev range 0..9999");
  }
  if (mode === "solver") {
    if (num < 3000 || num > 9999) {
      throw new RangeError("Solver mode requires public dev seed 3000..9999");
    }
  } else if (mode === "mole") {
    if (!(DEFAULT_DUEL_SEEDS.includes(num) || (num >= 3000 && num <= 9999))) {
      throw new RangeError("Mole mode requires seed 6, 26, or 3000..9999");
    }
  } else if (!((num >= 0 && num <= 29) || (num >= 3000 && num <= 9999))) {
    throw new RangeError("Duel or Living mode requires seed 0..29 or 3000..9999");
  }
  return num;
}

export function scrubPreEndValue(value, allowMoleIdentity = false) {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) {
    return value.map((item) => scrubPreEndValue(item, allowMoleIdentity));
  }
  if (typeof value !== "object") return value;
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    if (PRE_END_FORBIDDEN_KEYS.has(k)) continue;
    if (MOLE_DOC_HIDDEN_KEYS.has(k)) continue;
    if (k === "moleEmployee" && allowMoleIdentity) {
      out[k] = v && typeof v === "object" ? Object.assign({}, v) : v;
      continue;
    }
    out[k] = scrubPreEndValue(v, allowMoleIdentity);
  }
  return out;
}

function normalizeMolePublicState(rawView, tier, seed, debrief = null) {
  const v = rawView && typeof rawView === "object" ? rawView : {};
  const isDone = Boolean(v.done || (debrief && debrief.done));
  const empSrc = v.moleEmployee || v.employee || {
    id: v.mole_id || "e01",
    name: v.mole_name || "Assigned Insider",
    dept: v.mole_dept || "Operations",
    role: v.mole_role || "Analyst",
  };
  const rawDocs = Array.isArray(v.moleCandidateDocs)
    ? v.moleCandidateDocs
    : Array.isArray(v.leakable_docs)
      ? v.leakable_docs
      : Array.isArray(v.docs)
        ? v.docs
        : [];
  const safeDocs = rawDocs.map((doc) => {
    const cleanDoc = {};
    for (const [k, val] of Object.entries(doc || {})) {
      if (!isDone && (MOLE_DOC_HIDDEN_KEYS.has(k) || PRE_END_FORBIDDEN_KEYS.has(k))) {
        continue;
      }
      cleanDoc[k] = val;
    }
    return cleanDoc;
  });
  const visV =
    v.visibleV !== undefined
      ? Number(v.visibleV)
      : v.visible_v !== undefined
        ? Number(v.visible_v)
        : v.visible_V !== undefined
          ? Number(v.visible_V)
          : 1.0;
  const dayNum = Number(v.day || 1);
  const nDaysNum = Number(v.nDays || v.n_days || (tier === "hard" ? 21 : 14));
  const telemetryRaw = v.solverTelemetry || {
    day: dayNum,
    visible_V: visV,
    canaries_planted: Number(v.canaries_planted || 0),
    interviews_done: v.interviewed_today ? 1 : 0,
    restricted_count: Number(v.total_staff_restricted || 0),
    top_posterior_prob: Number(v.top_posterior_prob || 0),
    entropy_bits: Number(v.entropy_bits || 0),
  };
  const safeTelemetry = isDone ? telemetryRaw : scrubPreEndValue(telemetryRaw, false);
  let revealObj = null;
  if (isDone) {
    if (v.reveal && typeof v.reveal === "object") {
      revealObj = Object.assign({}, v.reveal);
    } else if (debrief && typeof debrief === "object") {
      revealObj = {
        moleId: debrief.mole_id || empSrc.id,
        moleName: debrief.mole_name || empSrc.name,
        accused: debrief.accused_id || null,
        caught: Boolean(debrief.caught),
        survived: Boolean(debrief.survived),
        humanMoleScore: Number(debrief.mole_score || 0),
        solverScore: Number(debrief.solver_score || 0),
        daysSurvived: Number(debrief.days_survived !== undefined ? debrief.days_survived : dayNum),
        leaksLanded: Number(debrief.leaks_count || 0),
      };
    }
  }
  return {
    ok: true,
    mode: "mole",
    tier,
    seed,
    day: dayNum,
    nDays: nDaysNum,
    visibleV: visV,
    done: isDone,
    canLeak: v.can_leak !== undefined ? Boolean(v.can_leak) : safeDocs.length > 0 && !isDone,
    moleEmployee: {
      id: String(empSrc.id || "e01"),
      name: String(empSrc.name || "Assigned Insider"),
      dept: String(empSrc.dept || empSrc.department || "Operations"),
      role: String(empSrc.role || "Staff"),
    },
    moleCandidateDocs: safeDocs,
    solverTelemetry: safeTelemetry,
    leaksLanded: Number(
      v.leaksLanded !== undefined
        ? v.leaksLanded
        : revealObj
          ? revealObj.leaksLanded
          : v.total_surfaced_leaks || 0
    ),
    daysSurvived: Number(
      v.daysSurvived !== undefined
        ? v.daysSurvived
        : revealObj
          ? revealObj.daysSurvived
          : Math.max(0, dayNum - 1)
    ),
    reveal: isDone ? revealObj : null,
  };
}

function normalizeMoleActionInput(action) {
  if (typeof action === "string" && action.trim()) {
    const id = action.trim();
    return { type: "leak", doc_id: id, leakDocId: id, frame_peer: null };
  }
  if (!action || typeof action !== "object") {
    return { type: "hold", doc_id: null, leakDocId: null, frame_peer: null };
  }
  const explicitDoc = action.leakDocId || action.doc_id || action.docId || null;
  const explicitType = String(action.type || action.action || "").trim().toLowerCase();
  const framePeer = action.frame_peer || action.framePeer || action.frame || null;
  if (explicitType === "hold" || (!explicitType && !explicitDoc)) {
    return { type: "hold", doc_id: null, leakDocId: null, frame_peer: framePeer };
  }
  if (explicitDoc) {
    const cleanId = String(explicitDoc).trim();
    return { type: "leak", doc_id: cleanId, leakDocId: cleanId, frame_peer: framePeer };
  }
  return { type: "hold", doc_id: null, leakDocId: null, frame_peer: framePeer };
}

async function defaultSafeImport(specifier) {
  try {
    const url = new URL(specifier, import.meta.url).href;
    return await import(url);
  } catch (_) {
    try {
      return await import(specifier);
    } catch (_err) {
      return null;
    }
  }
}

function stripLeadingPyPrefix(rawPath) {
  let clean = String(rawPath || "").trim();
  while (clean.startsWith("./")) {
    clean = clean.slice(2);
  }
  while (clean.startsWith("/")) {
    clean = clean.slice(1);
  }
  if (clean.startsWith("py/")) {
    clean = clean.slice(3);
  }
  return clean;
}

function ensurePyodideDir(fsObj, fullPath) {
  const slashIdx = fullPath.lastIndexOf("/");
  if (slashIdx <= 0) return;
  const dirPath = fullPath.slice(0, slashIdx);
  if (fsObj && typeof fsObj.mkdirTree === "function") {
    fsObj.mkdirTree(dirPath);
    return;
  }
  if (fsObj && typeof fsObj.mkdir === "function") {
    const parts = dirPath.split("/").filter(Boolean);
    let cur = "";
    for (const part of parts) {
      cur += "/" + part;
      try {
        fsObj.mkdir(cur);
      } catch (_) {}
    }
  }
}

function resolveRelativeAssetUrl(relPath, baseHref) {
  try {
    return new URL(relPath, baseHref || import.meta.url).href;
  } catch (_) {
    return relPath;
  }
}

function findByIdInTree(node, targetId) {
  if (!node) return null;
  if (node.id === targetId) return node;
  if (typeof node.getAttribute === "function" && node.getAttribute("id") === targetId) {
    return node;
  }
  const kids = node.childNodes || node.children || [];
  for (const child of kids) {
    const found = findByIdInTree(child, targetId);
    if (found) return found;
  }
  return null;
}

function findFirstByClass(node, clsToken) {
  if (!node) return null;
  const cls = String(
    node.className ||
      (typeof node.getAttribute === "function" && node.getAttribute("class")) ||
      ""
  );
  if (cls.split(/\s+/).includes(clsToken)) return node;
  const kids = node.childNodes || node.children || [];
  for (const child of kids) {
    const hit = findFirstByClass(child, clsToken);
    if (hit) return hit;
  }
  return null;
}

function parseInitialUrlParams(g) {
  const defaultDuelSeed = DEFAULT_DUEL_SEEDS.includes(26) ? 26 : DEFAULT_DUEL_SEEDS[0];
  const out = { mode: "duel", tier: "hard", seed: defaultDuelSeed };
  try {
    const search =
      g && g.location && typeof g.location.search === "string"
        ? g.location.search
        : "";
    if (!search) return out;
    const params = new URLSearchParams(search);
    const m = params.get("mode");
    if (m && VALID_MODE_IDS.has(m)) {
      out.mode = m;
      out.tier = m === "solver" || m === "mole" ? "medium" : "hard";
      out.seed = m === "solver" || m === "mole" ? 3000 : defaultDuelSeed;
    }
    const t = params.get("tier");
    if (t && VALID_TIERS.has(t)) {
      out.tier = t;
    }
    const s = params.get("seed");
    if (s !== null && s !== "") {
      out.seed = validateArenaSeed(s, out.mode);
    }
  } catch (_) {}
  return out;
}

function createPackBackedLivingAdapter(packObj) {
  if (!packObj || typeof packObj !== "object") return null;
  const episodes = packObj.episodes || packObj.cases || packObj.seeds || {};
  return {
    getBanner() {
      return String(packObj.banner || DEFAULT_LIVING_BANNER);
    },
    getAvailableSeeds(tier = "hard") {
      if (Array.isArray(packObj.available_seeds) && packObj.available_seeds.length) {
        return packObj.available_seeds.slice();
      }
      if (Array.isArray(packObj.seeds_list) && packObj.seeds_list.length) {
        return packObj.seeds_list.slice();
      }
      const found = [];
      for (const k of Object.keys(episodes)) {
        const parts = String(k).split(":");
        const sNum = Number(parts[parts.length - 1]);
        if (Number.isInteger(sNum) && (parts.length === 1 || parts[0] === tier)) {
          found.push(sNum);
        }
      }
      return found.length ? found : DEFAULT_DUEL_SEEDS.slice();
    },
    getDayState(seed, humanDay, humanDone, tier = "hard") {
      const ep = episodes[`${tier}:${seed}`] || episodes[String(seed)] || null;
      if (!ep || typeof ep !== "object") {
        return { day: humanDay, rumours: [], grudges: [], chat_feed: [] };
      }
      const dayCap = Math.max(1, Number(humanDay) || 1);
      if (ep.days && ep.days[String(dayCap)]) {
        const dayEntry = ep.days[String(dayCap)];
        return humanDone ? dayEntry : scrubPreEndValue(dayEntry, false);
      }
      const cleanEp = humanDone ? ep : scrubPreEndValue(ep, false);
      const filterArr = (arr) =>
        Array.isArray(arr)
          ? arr.filter((r) => !r || r.day === undefined || Number(r.day) <= dayCap)
          : [];
      return {
        day: dayCap,
        rumours: filterArr(cleanEp.rumours),
        grudges: filterArr(cleanEp.grudges),
        chat_feed: filterArr(cleanEp.chat_feed),
      };
    },
  };
}

export function createArenaOrchestrator(options = {}) {
  const g = options.globalObject || getGlobal();
  const importFn = options.importModule || defaultSafeImport;
  const initial = parseInitialUrlParams(g);

  const modules = {
    aiDuelPanel: null,
    humanDesk: null,
    endScreen: null,
    leaderboard: null,
    replayEngine: null,
    committedDuelPack: null,
    geminiReplaysJson: null,
    moleMode: null,
    livingOffice: null,
    livingOfficePack: null,
    solverLive: null,
    tiebreakTraces: null,
    moleRivals: null,
    shareCard: null,
    transcriptCommentary: null,
  };

  const pyState = {
    status: options.pyodide ? "ready" : "idle",
    pyodide: options.pyodide || null,
    manifestFiles: [],
    bridgeReady: false,
    bootPromise: null,
    error: null,
  };

  const chosenMode =
    options.initialMode && VALID_MODE_IDS.has(options.initialMode)
      ? options.initialMode
      : initial.mode;
  const chosenTier =
    options.initialTier && VALID_TIERS.has(options.initialTier)
      ? options.initialTier
      : options.initialMode && !options.initialTier
        ? chosenMode === "solver" || chosenMode === "mole"
          ? "medium"
          : "hard"
        : initial.tier;
  const chosenSeed =
    options.initialSeed !== undefined
      ? validateArenaSeed(options.initialSeed, chosenMode)
      : options.initialMode
        ? chosenMode === "solver" || chosenMode === "mole"
          ? 3000
          : DEFAULT_DUEL_SEEDS.includes(26)
            ? 26
            : DEFAULT_DUEL_SEEDS[0]
        : initial.seed;

  const state = {
    mode: chosenMode,
    tier: chosenTier,
    seed: chosenSeed,
    day: 1,
    nDays: chosenTier === "hard" ? 21 : 14,
    visibleV: 1.0,
    calls: 0,
    actionsUsed: 0,
    done: false,
    spec: null,
    reveal: null,
    molePublic: null,
  };

  let activeInvestigatorHandle = null;
  let activeMoleHandle = null;
  let mountedDoc = options.document || (g && g.document) || null;
  let mountedRoot = null;
  let uiApp = null;
  let liveAdapters = null;

  function resolveDuelPackAdapter() {
    if (options.duelPack) return options.duelPack;
    if (options.geminiReplays) return options.geminiReplays;
    const mod = modules.committedDuelPack;
    if (mod) {
      return mod.CANARY_DUEL_PACK || mod.committedDuelPack || mod.default || mod;
    }
    if (modules.geminiReplaysJson) return modules.geminiReplaysJson;
    return (g && (g.CANARY_DUEL_PACK || g.CANARY_GEMINI_REPLAYS)) || null;
  }

  function resolveReplayAdapter() {
    if (options.replayEngine) return options.replayEngine;
    const mod = modules.replayEngine;
    if (mod) {
      return mod.CanaryReplayEngine || mod.replayEngine || mod.default || mod;
    }
    return (g && g.CanaryReplayEngine) || null;
  }

  function resolveLivingAdapter() {
    if (options.livingOffice) return options.livingOffice;
    const mod = modules.livingOffice;
    if (mod) {
      return mod.CanaryLivingOffice || mod.livingOffice || mod.default || mod;
    }
    if (g && g.CanaryLivingOffice) return g.CanaryLivingOffice;
    const packMod = modules.livingOfficePack;
    const rawPack =
      (packMod &&
        (packMod.CANARY_LIVING_OFFICE_PACK ||
          packMod.livingOfficePack ||
          packMod.default ||
          packMod)) ||
      (g && g.CANARY_LIVING_OFFICE_PACK) ||
      null;
    return createPackBackedLivingAdapter(rawPack);
  }

  function resolveSolverAdapter() {
    if (options.solverLive) return options.solverLive;
    const mod = modules.solverLive;
    if (mod) {
      return mod.CanarySolverLive || mod.solverLive || mod.default || mod;
    }
    if (g && g.CanarySolverLive) return g.CanarySolverLive;
    if (pyState.pyodide && typeof pyState.pyodide.runPython === "function") {
      return {
        getSolverDayState(tier, seed, humanDay, humanDone) {
          ensurePythonBridgeInitialized(pyState.pyodide);
          const expr = `_arena_boot_bridge.solver_day_state_json(${JSON.stringify(tier)}, ${JSON.stringify(seed)}, ${JSON.stringify(humanDay)}, ${humanDone ? "True" : "False"})`;
          const raw = pyState.pyodide.runPython(expr);
          return typeof raw === "string" ? JSON.parse(raw) : raw;
        },
      };
    }
    return null;
  }

  function resolveTiebreakAdapter() {
    if (options.tiebreakTraces) return options.tiebreakTraces;
    const mod = modules.tiebreakTraces;
    if (mod) {
      return mod.CANARY_TIEBREAK_TRACES || mod.tiebreakTraces || mod.default || mod;
    }
    return (g && g.CANARY_TIEBREAK_TRACES) || null;
  }

  function resolveMoleRivalsAdapter() {
    if (options.moleRivals) return options.moleRivals;
    const mod = modules.moleRivals;
    if (mod) {
      return mod.CanaryMoleRivals || mod.moleRivals || mod.default || mod;
    }
    return (g && g.CanaryMoleRivals) || null;
  }

  function resolveShareAdapter() {
    if (options.shareCard) return options.shareCard;
    const mod = modules.shareCard;
    if (mod) {
      return mod.CanaryShareCard || mod.shareCard || mod.default || mod;
    }
    return (g && g.CanaryShareCard) || null;
  }

  function resolveCommentaryAdapter() {
    if (options.transcriptCommentary) return options.transcriptCommentary;
    const mod = modules.transcriptCommentary;
    if (mod) {
      return (
        mod.CanaryTranscriptCommentary ||
        mod.transcriptCommentary ||
        mod.default ||
        mod
      );
    }
    return (g && g.CanaryTranscriptCommentary) || null;
  }

  function ensurePythonBridgeInitialized(py) {
    if (!py || typeof py.runPython !== "function") return false;
    if (pyState.bridgeReady) return true;
    try {
      if (py.FS && typeof py.FS.writeFile === "function") {
        ensurePyodideDir(py.FS, "/home/pyodide/_arena_boot_bridge.py");
        py.FS.writeFile("/home/pyodide/_arena_boot_bridge.py", PYTHON_BRIDGE_SOURCE);
        py.runPython(
          "import sys\nif '/home/pyodide' not in sys.path:\n    sys.path.insert(0, '/home/pyodide')\nimport _arena_boot_bridge\n_arena_boot_bridge.refresh_modules()"
        );
      } else {
        py.runPython(PYTHON_BRIDGE_SOURCE);
      }
      pyState.bridgeReady = true;
      return true;
    } catch (_) {
      return false;
    }
  }

  function instantiatePythonInvestigatorHandle(mode, tier, seed) {
    const validSeed = validateArenaSeed(seed, mode || "duel");
    if (typeof options.createGame === "function") {
      return options.createGame(tier, validSeed, mode);
    }
    if (typeof options.createInvestigatorGame === "function") {
      return options.createInvestigatorGame({ mode, tier, seed: validSeed });
    }
    if (options.game) {
      return options.game;
    }
    const py = pyState.pyodide;
    if (!py || typeof py.runPython !== "function") return null;
    ensurePythonBridgeInitialized(py);
    const expr = `_arena_boot_bridge.make_investigator_case(${JSON.stringify(mode)}, ${JSON.stringify(tier)}, ${JSON.stringify(validSeed)})`;
    return py.runPython(expr);
  }

  function instantiatePythonMoleHandle(tier, seed) {
    const validSeed = validateArenaSeed(seed, "mole");
    if (typeof options.createMoleSession === "function") {
      return options.createMoleSession({ tier, seed: validSeed });
    }
    const jsMole =
      options.moleMode ||
      (modules.moleMode &&
        (modules.moleMode.CanaryMoleMode ||
          modules.moleMode.default ||
          modules.moleMode)) ||
      (g && g.CanaryMoleMode) ||
      null;
    if (jsMole && typeof jsMole.startSession === "function") {
      return jsMole.startSession({
        tier,
        seed: validSeed,
        pyodide: pyState.pyodide,
      });
    }
    const py = pyState.pyodide;
    if (!py || typeof py.runPython !== "function") return null;
    ensurePythonBridgeInitialized(py);
    const expr = `_arena_boot_bridge.make_mole_case(${JSON.stringify(tier)}, ${JSON.stringify(validSeed)})`;
    return py.runPython(expr);
  }

  function readMolePublicFromHandle(handle, tier, seed) {
    if (!handle) {
      return normalizeMolePublicState(
        {
          day: 1,
          n_days: tier === "hard" ? 21 : 14,
          visible_v: 1.0,
          done: false,
        },
        tier,
        seed,
        null
      );
    }
    let rawView = null;
    if (typeof handle.getPublicState === "function") {
      rawView = handle.getPublicState();
    } else if (typeof handle.day_view_json === "function") {
      rawView = JSON.parse(handle.day_view_json());
    } else if (typeof handle.get_mole_day_view === "function") {
      rawView = handle.get_mole_day_view();
    } else {
      rawView = handle;
    }

    const resolveView = (resolvedView) => {
      const doneFlag = Boolean(resolvedView && resolvedView.done === true);
      let debrief = null;
      if (doneFlag) {
        if (typeof handle.debrief_json === "function") {
          debrief = JSON.parse(handle.debrief_json());
        } else if (typeof handle.getDebrief === "function") {
          debrief = handle.getDebrief();
        } else if (typeof handle.get_mole_debrief === "function") {
          debrief = handle.get_mole_debrief();
        }
      }
      return normalizeMolePublicState(resolvedView, tier, seed, debrief);
    };

    if (rawView && typeof rawView.then === "function") {
      return rawView.then(resolveView);
    }
    return resolveView(rawView);
  }

  function createUnifiedMoleModeBridge() {
    if (options.moleMode && typeof options.moleMode.startSession === "function") {
      return {
        startSession(params = {}) {
          const t = params.tier || "medium";
          const s = validateArenaSeed(
            params.seed !== undefined ? params.seed : 3000,
            "mole"
          );
          const sess = options.moleMode.startSession({
            tier: t,
            seed: s,
            pyodide: params.pyodide || pyState.pyodide,
          });
          activeMoleHandle = sess;
          return wrapMoleSessionForUi(sess, t, s);
        },
      };
    }
    return {
      startSession(params = {}) {
        const t = params.tier || "medium";
        const s = validateArenaSeed(
          params.seed !== undefined ? params.seed : 3000,
          "mole"
        );
        const handle = instantiatePythonMoleHandle(t, s);
        if (handle && typeof handle.then === "function") {
          return handle.then((resolved) => {
            activeMoleHandle = resolved;
            return wrapMoleSessionForUi(resolved, t, s);
          });
        }
        activeMoleHandle = handle;
        return wrapMoleSessionForUi(handle, t, s);
      },
    };
  }

  function wrapMoleSessionForUi(handle, tier, seed) {
    if (!handle) return null;
    let latestPub = readMolePublicFromHandle(handle, tier, seed);
    state.molePublic = latestPub;
    return {
      getPublicState() {
        latestPub = readMolePublicFromHandle(handle, tier, seed);
        state.molePublic = latestPub;
        return latestPub;
      },
      stepDay(act) {
        const norm = normalizeMoleActionInput(act);
        let rawOut = null;
        if (typeof handle.stepDay === "function") {
          rawOut = handle.stepDay({
            leakDocId: norm.leakDocId,
            framePeer: norm.frame_peer,
          });
        } else if (typeof handle.step_json === "function") {
          const payload = { type: norm.type };
          if (norm.doc_id) payload.doc_id = norm.doc_id;
          if (norm.frame_peer) payload.frame_peer = norm.frame_peer;
          rawOut = JSON.parse(handle.step_json(JSON.stringify(payload)));
        } else if (typeof handle.step_mole_day === "function") {
          rawOut = handle.step_mole_day({
            type: norm.type,
            doc_id: norm.doc_id,
            frame_peer: norm.frame_peer,
          });
        }
        const afterStep = (res) => {
          latestPub = readMolePublicFromHandle(handle, tier, seed);
          state.molePublic = latestPub;
          return res;
        };
        if (rawOut && typeof rawOut.then === "function") {
          return rawOut.then(afterStep);
        }
        return afterStep(rawOut);
      },
    };
  }

  async function loadOptionalModules(overrides = {}) {
    const entries = await Promise.all(
      OPTIONAL_SIBLING_MODULES.map(async ([slot, relPath]) => {
        if (overrides && slot in overrides) {
          return [slot, overrides[slot]];
        }
        try {
          const loaded = await importFn(relPath);
          return [slot, loaded || null];
        } catch (_) {
          return [slot, null];
        }
      })
    );
    for (const [slot, mod] of entries) {
      modules[slot] = mod;
    }

    if (!resolveDuelPackAdapter() && !resolveReplayAdapter()) {
      const fetchFn =
        options.fetch ||
        (g && typeof g.fetch === "function" ? g.fetch.bind(g) : null);
      if (typeof fetchFn === "function") {
        try {
          const baseHref =
            options.baseUrl ||
            (typeof import.meta !== "undefined" ? import.meta.url : "");
          const r = await fetchFn(
            resolveRelativeAssetUrl(GEMINI_REPLAYS_JSON_PATH, baseHref)
          );
          if (r && r.ok) {
            modules.geminiReplaysJson = await r.json();
          }
        } catch (_) {}
      }
    }

    return Object.assign({}, modules);
  }

  function ensurePyodideStatusBadge() {
    if (!mountedRoot || !mountedDoc) return null;
    let badge = findByIdInTree(mountedRoot, "pyodideStatus");
    if (!badge) {
      const mastRight = findFirstByClass(mountedRoot, "arena-mast-right");
      if (mastRight) {
        badge = el(
          "span",
          {
            document: mountedDoc,
            id: "pyodideStatus",
            class: "t dim",
          },
          "offline / replay ready"
        );
        mastRight.appendChild(badge);
      }
    }
    if (badge) {
      if (pyState.status === "ready") {
        badge.textContent = "pyodide live";
        badge.className = "t ok";
      } else if (pyState.status === "loading") {
        badge.textContent = "booting pyodide";
        badge.className = "t hl";
      } else {
        badge.textContent = "offline / replay ready";
        badge.className = "t dim";
      }
    }
    return badge;
  }

  function waitForDeferredPyodideGlobal(doc, timeoutMs = 1500) {
    if (g && typeof g.loadPyodide === "function") {
      return Promise.resolve(g.loadPyodide);
    }
    if (!doc || typeof doc.getElementById !== "function") {
      return Promise.resolve(null);
    }
    const loaderTag = doc.getElementById("pyodideLoaderScript");
    if (!loaderTag || typeof loaderTag.addEventListener !== "function") {
      return Promise.resolve(null);
    }
    return new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        resolve(g && typeof g.loadPyodide === "function" ? g.loadPyodide : null);
      };
      const timer = setTimeout(finish, timeoutMs);
      loaderTag.addEventListener("load", () => {
        clearTimeout(timer);
        finish();
      });
      loaderTag.addEventListener("error", () => {
        clearTimeout(timer);
        finish();
      });
    });
  }

  async function bootPyodideRuntime(bootOpts = {}) {
    if (pyState.status === "ready" && pyState.pyodide && !bootOpts.forceReload) {
      ensurePythonBridgeInitialized(pyState.pyodide);
      ensurePyodideStatusBadge();
      return {
        ok: true,
        ready: true,
        status: "ready",
        files: pyState.manifestFiles.slice(),
        pyodide: pyState.pyodide,
      };
    }
    if (pyState.bootPromise && !bootOpts.forceReload) {
      return pyState.bootPromise;
    }

    const runBoot = async () => {
      const loadFn =
        bootOpts.loadPyodide ||
        options.loadPyodide ||
        (g && typeof g.loadPyodide === "function" ? g.loadPyodide : null) ||
        (await waitForDeferredPyodideGlobal(
          mountedDoc,
          bootOpts.scriptWaitMs !== undefined ? bootOpts.scriptWaitMs : 1200
        ));

      if (typeof loadFn !== "function") {
        pyState.status = "offline";
        ensurePyodideStatusBadge();
        return { ok: false, ready: false, status: "offline", files: [] };
      }

      const fetchFn =
        bootOpts.fetch ||
        options.fetch ||
        (g && typeof g.fetch === "function" ? g.fetch.bind(g) : null);
      if (typeof fetchFn !== "function") {
        pyState.status = "offline";
        ensurePyodideStatusBadge();
        return { ok: false, ready: false, status: "no_fetch", files: [] };
      }

      pyState.status = "loading";
      ensurePyodideStatusBadge();

      try {
        const py = await loadFn(bootOpts.pyodideConfig || undefined);
        const baseHref =
          bootOpts.baseUrl ||
          options.baseUrl ||
          (typeof import.meta !== "undefined" ? import.meta.url : "");
        const manifestUrl = resolveRelativeAssetUrl("./py/manifest.json", baseHref);
        const manifestResp = await fetchFn(manifestUrl);
        if (!manifestResp || !manifestResp.ok) {
          throw new Error("manifest fetch unavailable");
        }
        const manifestObj = await manifestResp.json();
        const fileList = Array.isArray(manifestObj)
          ? manifestObj.slice()
          : Array.isArray(manifestObj && manifestObj.files)
            ? manifestObj.files.slice()
            : [];

        const writtenFiles = [];
        for (const rawRel of fileList) {
          const cleanRel = stripLeadingPyPrefix(rawRel);
          const fileUrl = resolveRelativeAssetUrl("./py/" + cleanRel, baseHref);
          const resp = await fetchFn(fileUrl);
          if (!resp || !resp.ok) {
            throw new Error("failed loading python module " + cleanRel);
          }
          const srcText = await resp.text();
          const targetPath = "/home/pyodide/" + cleanRel;
          if (py.FS && typeof py.FS.writeFile === "function") {
            ensurePyodideDir(py.FS, targetPath);
            py.FS.writeFile(targetPath, srcText);
          }
          writtenFiles.push(cleanRel);
        }

        for (const extraEntry of ["arena_game.py", "mole_mode.py"]) {
          if (writtenFiles.includes(extraEntry)) continue;
          for (const candidateRel of ["./py/" + extraEntry, "./" + extraEntry]) {
            try {
              const extraResp = await fetchFn(
                resolveRelativeAssetUrl(candidateRel, baseHref)
              );
              if (extraResp && extraResp.ok) {
                const extraSrc = await extraResp.text();
                const dstPath = "/home/pyodide/" + extraEntry;
                if (py.FS && typeof py.FS.writeFile === "function") {
                  ensurePyodideDir(py.FS, dstPath);
                  py.FS.writeFile(dstPath, extraSrc);
                }
                writtenFiles.push(extraEntry);
                break;
              }
            } catch (_) {}
          }
        }

        pyState.pyodide = py;
        pyState.manifestFiles = writtenFiles;
        pyState.bridgeReady = false;
        ensurePythonBridgeInitialized(py);
        pyState.status = "ready";
        pyState.error = null;

        if (liveAdapters) {
          liveAdapters.pyodide = py;
          liveAdapters.solverLive = resolveSolverAdapter();
        }

        if (uiApp && typeof uiApp.getState === "function") {
          const cur = uiApp.getState();
          if (
            cur &&
            !cur.done &&
            Number(cur.calls || 0) === 0 &&
            typeof uiApp.loadSeed === "function"
          ) {
            uiApp.loadSeed(cur.seed, cur.tier);
          }
        }

        ensurePyodideStatusBadge();
        return {
          ok: true,
          ready: true,
          status: "ready",
          files: writtenFiles.slice(),
          pyodide: py,
        };
      } catch (err) {
        pyState.status = "offline";
        pyState.error = String(err && err.message ? err.message : err);
        ensurePyodideStatusBadge();
        return {
          ok: false,
          ready: false,
          status: "offline",
          error: pyState.error,
          files: [],
        };
      }
    };

    pyState.bootPromise = runBoot();
    return pyState.bootPromise;
  }

  function createDynamicAdapters(doc, bootOptions = {}) {
    const spriteManifestOpt =
      bootOptions.spriteManifest !== undefined
        ? bootOptions.spriteManifest
        : options.spriteManifest !== undefined
          ? options.spriteManifest
          : SPRITE_PACK_MANIFEST_PATH;

    const replayProxy = {
      listSeeds(tier) {
        const r = resolveReplayAdapter();
        if (r && typeof r.listSeeds === "function") return r.listSeeds(tier);
        const p = resolveDuelPackAdapter();
        if (p && Array.isArray(p.default_seeds) && p.default_seeds.length) {
          return p.default_seeds.slice();
        }
        return DEFAULT_DUEL_SEEDS.slice();
      },
      getDuelView(seed, humanDay, humanDone, tier) {
        const r = resolveReplayAdapter();
        if (r) {
          if (typeof r.getDuelView === "function") {
            return r.getDuelView(seed, humanDay, humanDone, tier);
          }
          if (typeof r.getDayState === "function") {
            return r.getDayState(seed, humanDay, humanDone, tier);
          }
        }
        const p = resolveDuelPackAdapter();
        if (p && p.episodes) {
          const ep = p.episodes[`${tier || "hard"}:${seed}`] || p.episodes[String(seed)];
          if (ep) {
            if (humanDone && typeof p.unlockPostGameReveal === "function") {
              return Object.assign({}, ep, {
                final: p.unlockPostGameReveal(tier || "hard", seed, true),
              });
            }
            return ep;
          }
        }
        return null;
      },
    };

    const solverProxy = {
      getSolverDayState(tier, seed, humanDay, humanDone) {
        const s = resolveSolverAdapter();
        if (s && typeof s.getSolverDayState === "function") {
          return s.getSolverDayState(tier, seed, humanDay, humanDone);
        }
        if (s && typeof s.get_solver_day_state === "function") {
          return s.get_solver_day_state(humanDay, humanDone);
        }
        return null;
      },
    };

    const livingProxy = {
      getBanner() {
        const lo = resolveLivingAdapter();
        return lo && typeof lo.getBanner === "function"
          ? lo.getBanner()
          : DEFAULT_LIVING_BANNER;
      },
      getAvailableSeeds(tier) {
        const lo = resolveLivingAdapter();
        return lo && typeof lo.getAvailableSeeds === "function"
          ? lo.getAvailableSeeds(tier)
          : DEFAULT_DUEL_SEEDS.slice();
      },
      getDayState(seed, humanDay, humanDone, tier) {
        const lo = resolveLivingAdapter();
        if (!lo) return { day: humanDay, rumours: [], grudges: [], chat_feed: [] };
        if (typeof lo.getDayState === "function") {
          return lo.getDayState(seed, humanDay, humanDone, tier);
        }
        if (typeof lo.renderDay === "function") {
          return lo.renderDay(seed, humanDay);
        }
        return { day: humanDay, rumours: [], grudges: [], chat_feed: [] };
      },
    };

    const adapters = {
      document: doc,
      storage:
        bootOptions.storage !== undefined ? bootOptions.storage : options.storage,
      initialMode: state.mode,
      initialTier: state.tier,
      initialSeed: state.seed,
      spriteManifest: spriteManifestOpt,
      assetCredits: KENNEY_ASSET_CREDITS,
      OfficeStage: bootOptions.OfficeStage || options.OfficeStage || OfficeStage,
      pyodide: pyState.pyodide,
      createGame(tier, seed, mode) {
        const m = mode || (uiApp ? uiApp.getState().mode : state.mode) || "duel";
        const handle = instantiatePythonInvestigatorHandle(m, tier, seed);
        activeInvestigatorHandle = handle;
        return handle;
      },
      replayEngine: bootOptions.replayEngine || options.replayEngine || replayProxy,
      duelPack: bootOptions.duelPack || resolveDuelPackAdapter(),
      geminiReplays:
        bootOptions.geminiReplays ||
        options.geminiReplays ||
        modules.geminiReplaysJson ||
        null,
      solverLive: bootOptions.solverLive || options.solverLive || solverProxy,
      moleMode: createUnifiedMoleModeBridge(),
      livingOffice: bootOptions.livingOffice || options.livingOffice || livingProxy,
      tiebreakTraces: bootOptions.tiebreakTraces || resolveTiebreakAdapter(),
      moleRivals: bootOptions.moleRivals || resolveMoleRivalsAdapter(),
      shareCard: bootOptions.shareCard || resolveShareAdapter(),
      transcriptCommentary:
        bootOptions.transcriptCommentary || resolveCommentaryAdapter(),
    };

    return adapters;
  }

  async function bootArena(bootOptions = {}) {
    if (bootOptions.document) {
      mountedDoc = bootOptions.document;
    }
    const doc = mountedDoc;
    if (doc) {
      setDocument(doc);
    }

    const rootNode =
      bootOptions.root ||
      (doc && typeof doc.getElementById === "function"
        ? doc.getElementById("arenaRoot") || doc.getElementById("arenaApp")
        : null);
    mountedRoot = rootNode;

    await loadOptionalModules(
      bootOptions.moduleOverrides || options.moduleOverrides || {}
    );

    if (rootNode && doc) {
      liveAdapters = createDynamicAdapters(doc, bootOptions);
      uiApp = mountArenaUI(rootNode, liveAdapters);
      ensurePyodideStatusBadge();
    }

    const pyPromise = bootPyodideRuntime(bootOptions);
    if (bootOptions.awaitPyodide) {
      await pyPromise;
    } else {
      pyPromise.catch(() => null);
    }

    return api;
  }

  function startInvestigatorCase(params = {}) {
    const reqMode =
      params.mode && VALID_MODE_IDS.has(params.mode) && params.mode !== "mole"
        ? params.mode
        : state.mode === "mole"
          ? "duel"
          : state.mode;
    const defaultTier = reqMode === "solver" ? "medium" : "hard";
    const reqTier =
      params.tier && VALID_TIERS.has(params.tier) ? params.tier : defaultTier;
    const defaultSeed =
      reqMode === "solver"
        ? 3000
        : DEFAULT_DUEL_SEEDS.includes(26)
          ? 26
          : DEFAULT_DUEL_SEEDS[0];
    const reqSeed = validateArenaSeed(
      params.seed !== undefined ? params.seed : defaultSeed,
      reqMode
    );

    state.mode = reqMode;
    state.tier = reqTier;
    state.seed = reqSeed;
    state.day = 1;
    state.nDays = reqTier === "hard" ? 21 : 14;
    state.visibleV = 1.0;
    state.calls = 0;
    state.actionsUsed = 0;
    state.done = false;
    state.reveal = null;
    state.spec = null;

    if (uiApp) {
      if (uiApp.getState().mode !== reqMode) {
        uiApp.setMode(reqMode);
      }
      uiApp.loadSeed(reqSeed, reqTier);
      ensurePyodideStatusBadge();
    } else {
      activeInvestigatorHandle = instantiatePythonInvestigatorHandle(
        reqMode,
        reqTier,
        reqSeed
      );
      if (
        activeInvestigatorHandle &&
        typeof activeInvestigatorHandle.spec_json === "function"
      ) {
        const parsed = JSON.parse(activeInvestigatorHandle.spec_json());
        state.spec = scrubPreEndValue(parsed, false);
      }
    }

    return Object.assign({}, getState(), {
      ok: true,
      ready: Boolean(activeInvestigatorHandle),
      spec: state.spec,
    });
  }

  function callTool(toolName, args = {}) {
    const name = String(toolName || "").trim();
    if (!Object.prototype.hasOwnProperty.call(TOOL_DEFS, name)) {
      throw new Error("Unknown Canary Arena tool: " + name);
    }
    if (uiApp && typeof uiApp.runHumanTool === "function") {
      if (uiApp.getState().mode === "mole") {
        return {
          ok: false,
          tool: name,
          args: args || {},
          data: {},
          error: "Investigator tools are disabled in Mole mode",
          done: false,
          reveal: null,
        };
      }
      const res = uiApp.runHumanTool(name, args || {});
      const formatOut = (reply) => {
        const cur = uiApp.getState();
        const safeData = cur.done
          ? (reply && reply.data) || {}
          : scrubPreEndValue((reply && reply.data) || {}, false);
        return {
          ok: Boolean(reply && reply.ok),
          tool: name,
          args: args || {},
          data: safeData,
          error: String((reply && reply.error) || ""),
          done: cur.done,
          day: cur.day,
          visibleV: cur.visibleV,
          calls: cur.calls,
          reveal: cur.done ? state.reveal : null,
        };
      };
      if (res && typeof res.then === "function") {
        return res.then(formatOut);
      }
      return formatOut(res);
    }

    if (!activeInvestigatorHandle) {
      return {
        ok: false,
        tool: name,
        args: args || {},
        data: {},
        error: "Environment runtime is still loading",
        done: false,
        day: state.day,
        visibleV: state.visibleV,
        calls: state.calls,
        reveal: null,
      };
    }

    const raw =
      typeof activeInvestigatorHandle.call_json === "function"
        ? JSON.parse(
            activeInvestigatorHandle.call_json(name, JSON.stringify(args || {}))
          )
        : activeInvestigatorHandle.callTool(name, args || {});

    state.calls += 1;
    const isDone = Boolean(raw && raw.done === true);
    const safeData = isDone
      ? (raw && raw.data) || {}
      : scrubPreEndValue((raw && raw.data) || {}, false);
    if (raw && raw.ok && safeData.day !== undefined) {
      state.day = Number(safeData.day);
    }
    if (raw && raw.ok && safeData.V !== undefined) {
      state.visibleV = Number(safeData.V);
    }
    if (isDone) {
      state.done = true;
      if (typeof activeInvestigatorHandle.reveal_json === "function") {
        state.reveal = JSON.parse(activeInvestigatorHandle.reveal_json());
      } else if (typeof activeInvestigatorHandle.reveal === "function") {
        state.reveal = activeInvestigatorHandle.reveal();
      }
    }
    return {
      ok: Boolean(raw && raw.ok),
      tool: name,
      args: args || {},
      data: safeData,
      error: String((raw && raw.error) || ""),
      done: state.done,
      day: state.day,
      visibleV: state.visibleV,
      calls: state.calls,
      reveal: state.done ? state.reveal : null,
    };
  }

  function startMoleCase(params = {}) {
    const reqTier =
      params.tier && (params.tier === "medium" || params.tier === "hard")
        ? params.tier
        : "medium";
    const reqSeed = validateArenaSeed(
      params.seed !== undefined ? params.seed : 3000,
      "mole"
    );
    state.mode = "mole";
    state.tier = reqTier;
    state.seed = reqSeed;
    if (uiApp) {
      uiApp.setMode("mole");
      uiApp.loadSeed(reqSeed, reqTier);
      ensurePyodideStatusBadge();
      return Object.assign(
        { ok: true, ready: Boolean(activeMoleHandle) },
        state.molePublic || uiApp.getState()
      );
    }
    activeMoleHandle = instantiatePythonMoleHandle(reqTier, reqSeed);
    const pub = readMolePublicFromHandle(activeMoleHandle, reqTier, reqSeed);
    state.molePublic = pub;
    state.day = pub.day;
    state.nDays = pub.nDays;
    state.visibleV = pub.visibleV;
    state.done = pub.done;
    state.reveal = pub.done ? pub.reveal : null;
    return Object.assign({ ready: Boolean(activeMoleHandle) }, pub);
  }

  function stepMoleDay(action = {}) {
    const norm = normalizeMoleActionInput(action);
    if (uiApp && typeof uiApp.stepMole === "function") {
      if (uiApp.getState().mode !== "mole") {
        return { ok: false, error: "Not in Mole mode", done: false, reveal: null };
      }
      const res = uiApp.stepMole(norm.leakDocId);
      const afterUi = () => state.molePublic || uiApp.getState();
      if (res && typeof res.then === "function") {
        return res.then(afterUi);
      }
      return afterUi();
    }
    if (!activeMoleHandle) {
      return {
        ok: false,
        ready: false,
        error: "Mole Python session is waiting for Pyodide runtime",
        mode: "mole",
        tier: state.tier,
        seed: state.seed,
        day: state.day,
        done: false,
        reveal: null,
      };
    }
    const wrapped = wrapMoleSessionForUi(activeMoleHandle, state.tier, state.seed);
    wrapped.stepDay(norm);
    return state.molePublic;
  }

  function setMode(nextMode) {
    if (!VALID_MODE_IDS.has(nextMode)) return getState();
    state.mode = nextMode;
    if (uiApp && typeof uiApp.setMode === "function") {
      uiApp.setMode(nextMode);
      ensurePyodideStatusBadge();
      return getState();
    }
    if (nextMode === "mole") {
      startMoleCase({ tier: "medium", seed: 3000 });
    } else if (nextMode === "solver") {
      startInvestigatorCase({ mode: "solver", tier: "medium", seed: 3000 });
    } else {
      startInvestigatorCase({
        mode: nextMode,
        tier: "hard",
        seed: DEFAULT_DUEL_SEEDS.includes(26) ? 26 : DEFAULT_DUEL_SEEDS[0],
      });
    }
    return getState();
  }

  function loadSeed(nextSeed, nextTier) {
    const currentMode = uiApp ? uiApp.getState().mode : state.mode;
    const valid = validateArenaSeed(nextSeed, currentMode);
    if (uiApp && typeof uiApp.loadSeed === "function") {
      uiApp.loadSeed(valid, nextTier);
      ensurePyodideStatusBadge();
      return getState();
    }
    if (currentMode === "mole") {
      startMoleCase({
        tier: nextTier || (valid >= 3000 ? "medium" : "hard"),
        seed: valid,
      });
    } else {
      startInvestigatorCase({
        mode: currentMode,
        tier: nextTier || state.tier,
        seed: valid,
      });
    }
    return getState();
  }

  function getState() {
    if (uiApp && typeof uiApp.getState === "function") {
      return Object.assign({}, uiApp.getState(), {
        pyodideStatus: pyState.status,
      });
    }
    return {
      mode: state.mode,
      tier: state.tier,
      seed: state.seed,
      day: state.day,
      nDays: state.nDays,
      visibleV: state.visibleV,
      actionsUsed: state.actionsUsed,
      calls: state.calls,
      done: state.done,
      leakingSpriteEmployee: null,
      pyodideStatus: pyState.status,
      reveal: state.done ? state.reveal : null,
    };
  }

  const api = {
    get root() {
      return uiApp ? uiApp.root : mountedRoot;
    },
    bootArena,
    bootPyodideRuntime,
    loadOptionalModules,
    startInvestigatorCase,
    callTool,
    runHumanTool(tool, args) {
      return uiApp ? uiApp.runHumanTool(tool, args) : callTool(tool, args);
    },
    startMoleCase,
    stepMoleDay,
    stepMole(leakDocId) {
      return uiApp ? uiApp.stepMole(leakDocId) : stepMoleDay({ leakDocId });
    },
    setMode,
    loadSeed,
    toggleAgentRaw() {
      return uiApp && typeof uiApp.toggleAgentRaw === "function"
        ? uiApp.toggleAgentRaw()
        : null;
    },
    openLeaderboard(mode) {
      return uiApp && typeof uiApp.openLeaderboard === "function"
        ? uiApp.openLeaderboard(mode)
        : null;
    },
    closeLeaderboard() {
      return uiApp && typeof uiApp.closeLeaderboard === "function"
        ? uiApp.closeLeaderboard()
        : null;
    },
    destroy() {
      if (uiApp && typeof uiApp.destroy === "function") {
        uiApp.destroy();
      }
      uiApp = null;
    },
    getState,
    getUi() {
      return uiApp;
    },
    getLoadedModules() {
      return Object.assign({}, modules);
    },
  };

  return api;
}

const defaultOrchestrator = createArenaOrchestrator();

export const bootArena = defaultOrchestrator.bootArena;
export const bootPyodideRuntime = defaultOrchestrator.bootPyodideRuntime;
export const loadOptionalModules = defaultOrchestrator.loadOptionalModules;
export const startInvestigatorCase = defaultOrchestrator.startInvestigatorCase;
export const callTool = defaultOrchestrator.callTool;
export const startMoleCase = defaultOrchestrator.startMoleCase;
export const stepMoleDay = defaultOrchestrator.stepMoleDay;
export const setMode = defaultOrchestrator.setMode;
export const loadSeed = defaultOrchestrator.loadSeed;
export const getState = defaultOrchestrator.getState;

export const CanaryArenaBoot = Object.assign({}, defaultOrchestrator, {
  createArenaOrchestrator,
  validateArenaSeed,
  scrubPreEndValue,
  mountArenaUI,
  OfficeStage,
  MODE_DEFS,
  TOOL_GROUPS,
  TOOL_DEFS,
  DEFAULT_DUEL_SEEDS,
  OPTIONAL_SIBLING_MODULES,
  KENNEY_ASSET_CREDITS,
  SPRITE_PACK_MANIFEST_PATH,
  PYODIDE_CDN_URL,
  sanitizeStepForPreEnd,
  scrubPreEndObject,
  sanitizeGeminiReplayState,
  sanitizeSolverLiveState,
  computeFirstCatchLabel,
  buildCanonicalShareLine,
});

const globalRef = getGlobal();
if (globalRef && typeof globalRef === "object") {
  globalRef.CanaryArenaUI = Object.assign(globalRef.CanaryArenaUI || {}, {
    mountArenaUI,
    OfficeStage,
    sanitizeStepForPreEnd,
    scrubPreEndObject,
    sanitizeGeminiReplayState,
    sanitizeSolverLiveState,
    computeFirstCatchLabel,
    buildCanonicalShareLine,
  });
  globalRef.mountArenaUI = mountArenaUI;
  globalRef.CanaryArenaBoot = CanaryArenaBoot;
}

if (globalRef && globalRef.document) {
  const tryAutoBoot = () => {
    if (
      typeof globalRef.document.getElementById === "function" &&
      (globalRef.document.getElementById("arenaRoot") ||
        globalRef.document.getElementById("arenaApp"))
    ) {
      defaultOrchestrator.bootArena().catch(() => null);
    }
  };
  if (
    globalRef.document.readyState === "loading" &&
    typeof globalRef.document.addEventListener === "function"
  ) {
    globalRef.document.addEventListener("DOMContentLoaded", tryAutoBoot, {
      once: true,
    });
  } else {
    tryAutoBoot();
  }
}
