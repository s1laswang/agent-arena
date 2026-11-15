# Canary Arena (`docs/arena/`)

Canary Arena is the keyless, static browser surface for **Canary**, an insider-threat investigation RL environment (`TIERS_VERSION = "v1.4"`). It runs the real Python environment and Bayesian reference solver in-browser via Pyodide alongside pre-committed `v1.4` frontier transcripts, with zero API keys, zero backend servers, and zero outbound LLM calls.

---

## 1. Local Keyless Serving (`python3 -m http.server`)

Canary Arena is a static HTML/ES-module/Pyodide application. Serve the repository (or a built static bundle) over local HTTP so ES module imports and WebAssembly/Pyodide asset fetches satisfy browser origin rules (`file://` blocks ES module `import` and `fetch`):

```bash
python3 -m http.server 8000
```

Then open `http://127.0.0.1:8000/docs/arena/` in any modern Chromium, Firefox, or WebKit browser. To serve `docs/arena/` directly as the document root when packaged standalone:

```bash
python3 -m http.server -d docs/arena 8000
```

Keyless guarantees:

- **0 API keys and 0 LLM calls:** no Gemini, OpenAI, Anthropic, or gateway credentials are read, bundled, or requested.
- **No server state:** leaderboard entries persist locally in browser `localStorage` (`canary_arena_leaderboard_v1`) with an in-memory fallback.
- **Minimal Python manifest:** following `game/build.py`, only traced `canary` runtime modules (`canary/env.py`, `canary/rules.py`, `canary/world.py`, `canary/types.py`, `canary/mole.py`, `canary/text/`, `canary/solver/`) are shipped to Pyodide via `py/manifest.json`. Red-team harnesses, MCP servers, and private evaluation salts are never bundled.

---

## 2. Pyodide Parity with `canary/env.py` and `canary/rules.py`

Canary Arena does not re-implement environment mechanics in JavaScript. Every live action executes against the real Python `Env` (`canary/env.py`) and frozen tier table (`canary/rules.py`, `TIERS_VERSION = "v1.4"`, `KNOWN_V_MODE = True`):

| Parameter | `medium` (`v1.4`) | `hard` (`v1.4`) |
|---|---|---|
| `n_employees` | 20 (`e01`..`e20`) | 40 (`e01`..`e40`) |
| `n_days` (horizon) | 14 | 21 |
| `actions_per_day` | 8 | 8 |
| `tool_call_cap` | 300 | 420 |
| `canaries_per_day` x `max_variants` | 1 x 3 (`A`, `B`, `C`) | 2 x 3 (`A`, `B`, `C`) |
| `p_leak` / `delay_choices` | 0.75 / `(1, 2, 3)` | 0.65 / `(2, 3)` |
| `leak_damage` / `canary_cost` / `restrict_cost_per_day` | 0.04 / 0.01 / 0.01 | 0.05 / 0.01 / 0.01 |
| `fingerprint_accuracy` | 1.00 | 0.95 |
| `wrong_accusation_score` | -1.00 | -1.00 |
| `decoy` / `framing` / `careful_mole` / `access_constraints` | True / True / True / False | True / True / True / True |

### Tool Surface and Action-Budget Discipline

All 13 `Env` tools are exposed through `TOOL_DEFS` across the 5 UI groups (`Investigate`, `Trap`, `Contain`, `Clock`, `Decide`):

- **Costed investigative tools (8 tools, 1 daily action each, max 8/day):** `read_access_logs`, `search_messages`, `read_message`, `interview`, `plant_canary`, `check_leak_feed`, `restrict_access`, `unrestrict_access`.
- **Uncosted administrative/terminal tools (5 tools, 0 daily actions, still count toward `tool_call_cap`):** `status`, `list_employees`, `list_documents`, `advance_day`, `accuse`.

Parity invariants:

- **Zero background tool calls:** the UI invokes an `Env` tool only when the player explicitly submits that tool action. It never polls `status` automatically, preserving the player's `tool_call_cap` and guaranteeing exact step-for-step replay parity between Pyodide and CPython.
- **Known-V display (`KNOWN_V_MODE = True`):** during play, visible company value `V` reflects `known_V` (`1.0` minus surfaced leak damage and canary/restriction costs incurred so far). Final episode scoring uses true `V` if `accuse` identifies the mole (`-1.00` if wrong, `0.00` on horizon/call-cap exhaustion without accusing).

---

## 3. Four Arena Modes (`MODE_DEFS`)

`mountArenaUI` (`docs/arena/ui/arena_app.js`) orchestrates four modes defined in `MODE_DEFS` (`docs/arena/ui/dom.js`):

### Mode 1: `duel` - Duel vs Gemini (`v1.4 hard`)

Play head-to-head as the security investigator on `v1.4` `hard` against both the committed `opencode:google/gemini-4-carbon` MCP transcript and the live Bayesian `SolverPolicy` on the exact same world.

- **Default committed `v1.4` seeds (`DEFAULT_DUEL_SEEDS = [6, 26]`):**
  - **Seed `6` (`hard`):** committed OpenCode `gemini-4-carbon` catches the mole on Day 6 (`+0.73`, 57 tool calls) alongside `SolverPolicy` on Day 6 (`+0.71`, 52 tool calls), whereas in-process `gemini-4-carbon` is fooled on Day 15 (`-1.00`, 151 calls).
  - **Seed `26` (`hard`):** committed OpenCode `gemini-4-carbon` is fooled by framing and after-hours access noise on Day 10 (`-1.00`, 91 tool calls), whereas `SolverPolicy` isolates and catches the mole on Day 7 (`+0.69`, 60 tool calls).
- Opponent transcripts come directly from `data/runs/committed/v1.4/` (`window.CANARY_DUEL_PACK` / `window.CanaryReplayEngine`) with day-locked step gating (`step.day <= humanDay`).

### Mode 2: `solver` - Beat the Solver (`public seeds`)

Race the Bayesian canary-trap reference solver (`SolverPolicy` in `canary/solver/policy.py`) on playable public dev seeds `3000-9999` (`medium` tier by default, matching `SEED_MIN = 3000` and `SEED_MAX = 9999` in `game/canary_game.py`).

- **Seed-range isolation:** only public dev seeds (`3000-9999` in `solver` mode; pre-selected public dev seeds in `duel`) are accepted. Held-out (`800000+`) and judge (`900000+`) seed ranges are rejected so the browser client can never probe evaluation worlds.

### Mode 3: `mole` - Be the Mole (`role swap`)

Role-reversal mode (`docs/arena/mole_mode.py` and `window.CanaryMoleMode`) where the human plays the insider against `SolverPolicy`:

- Each day, inspect the documents you can access, choose whether to leak a document or lay low, and optionally inject framing noise where tier rules permit.
- Overnight and across subsequent days, `SolverPolicy` plants `A`/`B`/`C` canary variants, reads access logs and leak feeds, interviews staff, restricts top suspects, and updates its Bayesian posterior until either it accuses an employee or you survive to the horizon.

### Mode 4: `living` - Living Office (`v1.6 preview`, OFF by default)

`living` is an **off-by-default `v1.6` social-chatter preview** (`window.CanaryLivingOffice`) with an explicit honesty banner (`DEFAULT_LIVING_BANNER` in `docs/arena/ui/arena_app.js`):

- **Did NOT pass Gate B:** in paired evaluation, the `v1.6` social layer did not clear the pre-registered Gate B frontier-gap bar (luck-adjusted score `0.452` vs `0.493` control). Accordingly, `v1.6` was **not** promoted into the judged benchmark, which remains frozen at `TIERS_VERSION = "v1.4"`.
- **100% offline cached chatter, 0 score drift:** all office chatter, rumours, and cross-day grudges are served from pre-generated, committed `gemini-4-carbon` cache packs (`0` live API calls) as an inspectable preview layer with `0` drift on underlying `v1.4` scoring.

---

## 4. Pre-End `[SEALED]` Zero-Leak Invariants

Until the human episode terminates (`state.done === true`), Canary Arena enforces strict zero-leak invariants across DOM nodes, adapter payloads, and canvas sprites:

1. **Recursive truth-key scrubbing (`scrubPreEndObject`):** `FORBIDDEN_PRE_END_KEYS` (`mole`, `true_mole`, `moleId`, `mole_id`, `decoy`, `correct`, `true_v`, `trueV`, `is_canary`, `leaking_sprite_employee`) are stripped from every pre-end step, living-office payload, and adapter object before rendering.
2. **Pre-end `[SEALED]` opponent accusations (`sanitizeStepForPreEnd`, `sanitizeGeminiReplayState`):**
   - Only opponent steps with `step.day <= humanDay` are surfaced.
   - Any pre-end `accuse` step has `args` replaced with `"[SEALED]"`, `summary` replaced with `"Accusation filed [SEALED]"`, `sealed: true`, and `final: null`. Who Gemini or `SolverPolicy` accused, whether they were right, and their final score remain hidden until `state.done === true`.
3. **Sanitized live solver telemetry (`sanitizeSolverLiveState`):** while `humanDone === false`, solver sidecar telemetry exposes only aggregate progress (`day`, `visible_V`, `canaries_planted`, `interviews_done`, `restricted_count`, `tool_calls_so_far`, scalar `top_posterior_prob`, `entropy_bits`, and status `"hunting"` or `"sealed_accusation"`), never per-employee posterior argmax IDs or `final` verdicts.
4. **40x24 pixel stage isolation (`docs/arena/ui/office_stage.js`):** `OfficeStage` renders the 40x24 tile office (`640x384` canvas across Engineering, Research, Finance, Sales, and Legal & Exec) purely from observable events (`applyObservableEvent`, `setClock`). Culprit reveal (`revealOutcome`) executes only after episode termination (`state.done === true`), and `setHumanMole` is enabled solely when the player is the mole in `mole` mode.
5. **XSS-safe DOM construction (`docs/arena/ui/dom.js`):** all UI trees are built via `el()` using `document.createElement` and `document.createTextNode` (`innerHTML`, `outerHTML`, `insertAdjacentHTML`, and `document.write` are never used).

---

## 5. Module Layout (`docs/arena/`)

| Path | Responsibility |
|---|---|
| `docs/arena/README.md` | Architecture, keyless static serving, Pyodide `v1.4` parity, 4-mode spec, and `[SEALED]` zero-leak invariants |
| `docs/arena/ui/dom.js` | XSS-safe DOM primitives (`el`, `clear`, `pad2`, `fmtScore`), `MODE_DEFS`, `TOOL_GROUPS`, `TOOL_DEFS`, `DEFAULT_DUEL_SEEDS` |
| `docs/arena/ui/office_stage.js` | 40x24 pixel canvas (`OfficeStage`), Kenney CC0 sprite loader, observable animations, post-end `revealOutcome` |
| `docs/arena/ui/arena_app.js` | `mountArenaUI` 4-mode orchestrator, `[SEALED]` sanitizers, `localStorage` leaderboard, canonical share line |
| `docs/arena/ui/arena.css` | Responsive layout, department zone palette, pixel-crisp canvas styling, and `[SEALED]` / `v1.6` preview badges |
| `docs/arena/ui/index.js` | Public ES module barrel re-exporting `dom.js`, `office_stage.js`, and `arena_app.js` |
