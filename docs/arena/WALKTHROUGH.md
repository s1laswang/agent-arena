# Canary Arena: 90-Second Judge Playable Walkthrough

**Frozen benchmark:** `TIERS_VERSION = "v1.4"` (SHA-256 `a8f99c2537c91d72` in [`canary/rules.py`](../../canary/rules.py)) | **Runtime:** 100% offline/client-side (`0` API keys, `0` live LLM calls)  
**Companion docs:** [`README.md`](../../README.md) | [`paired_table_gemini.md`](../../data/runs/committed/v1.4/paired_table_gemini.md) | [`docs/reports/gap.md`](../reports/gap.md) | [`docs/reports/failure_gallery.md`](../reports/failure_gallery.md)

Canary Arena puts a judge inside the exact `13`-tool insider-leak environment (`Investigate`, `Trap`, `Contain`, `Clock`, `Decide` in [`docs/arena/ui/dom.js`](ui/dom.js)) alongside committed `opencode:google/gemini-4-carbon` transcripts and the live Bayesian canary-trap `SolverPolicy`. Every opponent trace is replay-verified against `Env`, and every secret remains **`[SEALED]`** until your episode terminates.

---

## 90-Second Judge Click Path

| Window | Mode (`MODE_DEFS` id / badge) | What to Click & Observe | Grounded Benchmark Fact |
|---|---|---|---|
| **`0:00-0:30`** | **Mode 1: Duel vs Gemini** (`duel` / `v1.4 hard`, default `Seeds 6 & 26`) | Start on **Seed `26`** (or **Seed `6`**), plant a Day 1-2 `plant_canary` split (`A`/`B`/`C`), advance days (`advance_day`), check `check_leak_feed`, and watch the synchronized right-hand AI pane stay **`[SEALED]`** until you `accuse`. | **Seed `6`:** both `gemini-4-carbon` (`+0.73`, `57` calls, `7` canaries) and `SolverPolicy` (`+0.71`, `52` calls, `9` canaries) catch the mole on **day `6`**. **Seed `26`:** `SolverPolicy` plants `11` canaries by day `6` and wins on **day `7` (`+0.69`, `60` calls)**; `gemini-4-carbon` runs `43` interviews, plants late canaries, gets fooled on **day `10`** by a `1-in-20` noisy readout (`S1`), and accuses an innocent decoy (**`-1.00`, `91` calls**). |
| **`0:30-0:55`** | **Mode 2: Beat the Solver** (`solver` / `public seeds`, `seeds 3000-9999`) | Switch to **Beat the Solver**, pick any public dev seed in **`3000-9999`** (for example `3000`), run your canary traps, and submit `accuse` to unlock the same-seed `SolverPolicy` comparison. | Runs `Env` + `SolverPolicy` in Pyodide ([`game/canary_game.py`](../../game/canary_game.py)). Seeds outside `3000-9999` (judge seeds `900000+`, locked dev seeds `0-59`, training seeds) are strictly refused (`Medium seed 3000`: solver `+0.79` on day `6`). |
| **`0:55-1:15`** | **Mode 3: Be the Mole** (`mole` / `role swap`, `seeds 3000-9999`) | Switch to **Be the Mole** on any public seed in **`3000-9999`**. Inspect your daily document inbox under `MoleView` and decide what to leak or hold back each night. | You never see which inbox documents carry hidden `plant_canary` variant watermarks (`A`/`B`/`C`) while `SolverPolicy` plants splits, updates its Bayesian posterior, restricts suspects, and tries to accuse you before company value `V` drains. |
| **`1:15-1:30`** | **Mode 4: Living Office** (`living` / `v1.6 preview`, **off by default**) | Toggle the opt-in **Living Office** preview drawer (`v1.6 preview`) to inspect cached multi-day workplace chatter, rumours, authority theories, and grudge threads. | **Did NOT pass Gate B (off by default):** replays offline-cached `PublicDayFacts` text (`LR = 1.0`, `solver_calibration_diff = 0.0`, `0` API calls). Neither `v1.5-candidate` (`108%` vs `61%` on hard seeds `0-9`) nor `v1.6` passed **Gate B**, so frozen `v1.4` (`CANARY_PROVIDER=template`) is the sole judged environment. |

---

## Mode-by-Mode Reference

### 1. Mode 1: Duel vs Gemini (`duel` - `Seeds 6 & 26` vs `gemini-4-carbon` + `SolverPolicy`)

- **Default duel pair (`DEFAULT_DUEL_SEEDS = [6, 26]`):** Pairs a clean frontier success against a signature noisy-channel failure from the committed `v1.4` `hard` OpenCode MCP run (`n=30`, `seeds 0-29`, headline `65% [24%, 98%]` raw, `72% [52%, 91%]` luck-adjusted; note that `seeds 0-29` are a **post-hoc lock** where `671ed96` landed `28 s` after `8fd4dec`, not a pre-registration).
- **Seed `6` (`v1.4` `hard` calibration control):** Both `opencode:google/gemini-4-carbon` and `SolverPolicy` plant canary splits from Day `1` and accuse the true mole on **day `6`** (`gemini-4-carbon` `+0.73` across `57` tool calls with `7` canaries and `25` interviews; `SolverPolicy` `+0.71` across `52` tool calls with `9` canaries and `0` interviews).
- **Seed `26` (`v1.4` `hard` "Fooled" failure):** `SolverPolicy` plants `11` watermarked canaries across Days `1-6`, absorbs hard-tier `5%` readout noise, and accuses the true mole on **day `7` (`+0.69`, `60` tool calls)**. `gemini-4-carbon` spends `43` interviews on weak demeanour signals, plants its first canary on Day `4` (`8` total), treats a corrupted `S1` readout on **day `10`** as dispositive, and accuses an innocent employee for **`-1.00` (`91` tool calls)**.

### 2. Mode 2: Beat the Solver (`solver` - Public Seeds `3000-9999`)

- **Public seed firewall (`3000-9999` only):** `check_seed` in [`game/canary_game.py`](../../game/canary_game.py) enforces `SEED_MIN = 3000` and `SEED_MAX = 9999`. Any attempt to load judge seeds (`900000..900039`), locked frontier evaluation seeds (`0..59`), or training seeds raises `ValueError` so Arena can never be used to scout benchmark worlds.
- **Zero hidden budget spend:** The UI invokes an `Env` tool only when you click a tool action; it never polls `status` in the background.

### 3. Mode 3: Be the Mole (`mole` - Insider Role Swap)

- **Exact `MoleView` information boundary:** On public dev seeds `3000-9999`, you step into the insider's seat. Each day you see only the documents delivered to your clearance/department inbox and choose whether to leak a high-value document or lie low, without knowing which documents are watermarked `plant_canary` traps.
- **Live Bayesian adversary:** Overnight and each following day, `SolverPolicy` observes surfaced leaks (`leak_delay`), partitions suspects with `A`/`B`/`C` canary variants, applies `restrict_access` containment when warranted, and accuses as soon as expected stopping utility peaks.

### 4. Mode 4: Living Office (`living` - `v1.6` Cached Chatter Preview, Off by Default)

- **Offline-cached workplace dynamics:** Renders pre-generated `v1.6` corporate messages, rumours, senior-authority endorsements, and dyadic grudges (`.social-drawer`, `.rumour-item`, `.grudge-pill` in [`docs/arena/ui/arena.css`](ui/arena.css)) built strictly from `PublicDayFacts` (`LR = 1.0` zero mole leakage, `0` live API calls).
- **Honest Gate B disclosure:** Living Office is **off by default** and badged `v1.6 preview`. Under the project's Gate B rule, `v1.5-candidate` (`108%` vs `61%` on hard seeds `0-9`, [`docs/reports/gap.md`](../reports/gap.md)) and `v1.6` **did NOT pass Gate B**, so `v1.4` (`CANARY_PROVIDER=template`) ships unchanged as the sole judged benchmark.

---

## `[SEALED]` Pre-End Zero-Leak Integrity & XSS-Safe UI Contract

1. **`[SEALED]` pre-end redaction:** Throughout an active episode (`done == false`), `sanitizeStepForPreEnd`, `sanitizeGeminiReplayState`, and `sanitizeSolverLiveState` in [`docs/arena/ui/index.js`](ui/index.js) (`mountArenaUI` + `40x24` `OfficeStage`) mask the true mole ID, unsurfaced leak damage (true `V` vs visible `V`), `gemini-4-carbon` target employee IDs and accusation text, and `SolverPolicy` posterior argmax / final verdict behind **`[SEALED]`** badges. Calling `reveal_json()` prior to episode termination returns `{"error": "the episode is not over yet"}`; full head-to-head attribution (`revealOutcome`) unlocks only after `accuse` or horizon exhaustion.
2. **XSS-safe, comment-free ASCII UI (`docs/arena/ui/**`):** Every UI module constructs DOM nodes exclusively via `createElement` + `createTextNode` in [`docs/arena/ui/dom.js`](ui/dom.js). [`scripts/verify_arena_ui_contract.py`](../../scripts/verify_arena_ui_contract.py) (`--check`) enforces pure ASCII, `0` comments (`//`, `/*`, `*/`), `0` em dashes, `0` unsafe HTML sinks (`innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`), and `0` modifications to protected benchmark paths (`canary/env.py`, `canary/rules.py`, `canary/solver/`, `canary/reproduce.py`, `harbor/`).

```bash
uv run python scripts/demo_replay.py --seed 6 --verify
uv run python scripts/demo_replay.py --seed 26 --verify
uv run python scripts/verify_arena_ui_contract.py --check
uv run pytest -q tests/test_arena_ui_contract.py
```
