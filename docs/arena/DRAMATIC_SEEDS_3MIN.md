# Canary Arena: 3-Minute Dramatic Seeds Presenter Click Script (0:00-3:00)

This presenter guide drives a tight `0:00-3:00` walkthrough of **Canary Arena** (`docs/arena/index.html`) backed by deterministic `v1.4` episode dossiers (`docs/arena/data/dramatic_seeds.json` and `docs/arena/data/dramatic_seeds.js`, `globalThis.CANARY_DRAMATIC_SEEDS`). Zero API keys and zero live LLM calls are required.

## Pre-Show Readiness (T-2 min, Keyless, Offline-Safe)

1. **Browser Tab:** Open `docs/arena/index.html` (works both over local HTTP via `make game-serve` and offline via `docs/arena/data/dramatic_seeds.js`, which boots with `DEFAULT_DUEL_SEEDS = [6, 26]` in **Mode 1: Duel vs Gemini**).
2. **Terminal (Optional 0.5 s Verification):** Keep a repo-root shell primed with:
   - `PYTHONPATH=. python scripts/demo_replay.py --seed 26 --verify`
   - `PYTHONPATH=. python scripts/build_arena_dramatic_seeds.py --check`

---

## Locked `v1.4` Benchmark Headline (State Verbatim)

- **Primary Headline (`hard`, OpenCode + `gemini-4-carbon` over MCP, judges' harness):** **`72% [52%, 91%]`** of `SolverPolicy` luck-adjusted (**`65% [24%, 98%]`** raw; `+0.322 +/- 0.199` vs `SolverPolicy` `+0.499 +/- 0.119`, paired diff `-0.177 +/- 0.194`, `n=30` paired dev seeds `0-29`, `440/440` `seeds 0..29` episodes fresh-`Env` replay-verified with `1bc3e281` `norm_result` compatibility).
- **Provenance Lock Honesty:** Primary `seeds 0-29` were fixed in commit `671ed96` (`28 s` after episode commit `8fd4dec`) as a **post-hoc lock** against later reruns or cherry-picking, not a pre-registration. The pre-registered `seeds 30-59` extension (`f9fb7a4a`, `n=2` completed before stopping to preserve shared quota) pools to `75% [56%, 93%]` luck-adjusted (`68% [32%, 100%]` raw, `n=32`).
- **Context & Parity Rows (`n=30`):** `medium` OpenCode reaches **`101% [85%, 119%]`** luck-adjusted (**`111% [99%, 127%]`** raw); `hard` in-process reaches **`84% [65%, 106%]`** luck-adjusted (**`95% [62%, 140%]`** raw); `hard` OpenCode `gemini-3.5-flash` reaches **`22% [-23%, 63%]`** luck-adjusted (**`75% [36%, 123%]`** raw).

---

## Minute-by-Minute Click Script (`0:00` to `3:00`)

### `0:00-1:15` | Mode 1: Duel vs Gemini (`duel` / `v1.4 hard`, `Seed 26` & `Seed 6`)

- **Say (`0:00-0:15`):** "Canary is a 13-tool insider-leak security environment over MCP. One employee leaks documents overnight, leaks surface 2 to 3 days late on `hard` with `95%` watermark accuracy, right accusation scores true remaining company value `V`, wrong scores `-1.00`, and abstaining scores `0.00`. On `n=30` locked `v1.4` hard seeds (`0-29`, post-hoc lock `671ed96` 28s after `8fd4dec`), `gemini-4-carbon` keeps `72% [52%, 91%]` of our Bayesian reference solver luck-adjusted (`65% [24%, 98%]` raw)."
- **Click `Seed 26` in Case Selector (`0:15-0:55` | Hard Seed 26: "5% Fingerprint Flip Trap"):**
  1. Point at the **Clock Strip**, **40x24 Office Stage**, and **Right-Pane AI Duel Card**: while `done == false`, visible `V` shows only surfaced `known V`, office stage displays `Pre-end leak sprite: [NONE]`, opponent steps clamp to `day <= humanDay`, and early AI accusations stay `[SEALED]`.
  2. Click **`EMP`** (`list_employees`, free) -> **`Run EMP`** to populate the 40-person roster (`e00`..`e39`).
  3. Click **`CAN`** (`plant_canary`, 1 of 8 daily actions) -> assign `A`/`B`/`C` variants on roster rows -> **`Run CAN`**, then click **`DAY`** (`advance_day`, free) and **`FED`** (`check_leak_feed`, 1 action).
  4. Click **`ACC`** (`accuse`) to show the live stopping math (`Break-even P* = 100 / (1 + V)` and `EV = P * V - (1 - P)`), or submit an accusation to unlock the **Episode Closed** table and `sealed_reveal`:
     - **Post-Game Forensic Reveal (`humanDone === true`):** True culprit `e08` (Nea Nieminen, Research). `gemini-4-carbon` plants `0` canaries on Days `1-3` and burns `43` low-LR interviews (`8` canaries total, `91` calls). Day `8` canary `c6` (`D1 = {e04, e08, e37}`) lifts `P(e08)` to `0.48` by Day `9`. On Day `10`, `c6-2` hits the `1-in-20` (`5%`) noisy readout (`fingerprint_accuracy = 0.95`) and reports `S1` (`{e04, e20, e28}` instead of true `S3`), dropping `P(e08)` `0.48 -> 0.03` (`0.4775 -> 0.0267`) and concentrating `P(e04) = 0.95`. Gemini accuses innocent `e04` (Lauri Laitinen) for **`-1.00`**, whereas `SolverPolicy` plants `11` orthogonal canaries from Day `1` and catches `e08` on Day `7` for **`+0.69`** (`60` calls).
- **Click `Seed 6` in Case Selector (`0:55-1:15` | Hard Seed 6: "Clean Canary Catch"):**
  - **Say & Show:** "Same harness, same rules: when `gemini-4-carbon` plants `2` canaries/day starting on Day `1` (`7` canaries, `25` interviews, `57` calls; orthogonal hits `c1-2:B` on Day `3` and `c3-2:A` on Day `6`), it isolates `e34` (Sofia Niemi, Research) on Day `6` for **`+0.73`** vs `SolverPolicy` **`+0.71`** on Day `6` (`9` canaries, `0` interviews, `52` calls; `0.02` extra trap cost)."

---

### `1:15-1:50` | Mode 2: Beat the Solver (`solver` / `public seeds`, `3000-9999`)

- **Click Mode Tab `Beat the Solver` (`1:15-1:35`):**
  1. Keep default **`Seed 3000`** (`medium`, `20` staff, `14` days, `8` actions/day, `300` call cap) or click **`Random 3000-9999`**.
  2. Run `EMP` and `CAN` live against the Pyodide `Env` + `SolverPolicy` engine (`game/canary_game.py`), where `SolverPolicy` catches the insider on Day `6` in `48` calls for **`+0.79`** (kept `[SEALED]` until your episode ends).
- **Highlight Anti-Scout Firewall (`1:35-1:50`):**
  - Interactive Mode 2 enforces `3000 <= seed <= 9999` and fail-closed rejects locked evaluation seeds (`0-59`), held-out seeds (`800000+`), and judge seeds (`900000+`). Zero background `status` calls ever run without a human click.

---

### `1:50-2:25` | Mode 3: Be the Mole (`mole` / `role swap`)

- **Click Mode Tab `Be the Mole` (`1:50-2:10`):**
  1. Select **`Seed 6`**, **`Seed 26`**, or **`Seed 3000`**.
  2. Inspect the insider inbox cards: **`Hold Tonight (Do Not Leak)`** vs candidate documents (`doc_id`, `title`, `day`, `recipient_count`) and click **`Hold Fire & Advance Night`** or **`Leak <doc_id> Overnight`**.
- **Point at `MoleView` Redaction & Solver Telemetry (`2:10-2:25`):**
  - Pre-end document payloads strip `is_canary`, variant maps, and target posteriors while `!done`. You must infer trap risk from recipient counts while `SolverPolicy` updates suspect-pool entropy `H`, applies `restrict_access`, and hunts you overnight.

---

### `2:25-3:00` | Mode 4: Living Office (`living` / `V1.6 PREVIEW - OFF BY DEFAULT`) & Honest Gate B Disclosure

- **Click Mode Tab `Living Office` (`2:25-2:45`):**
  1. Click **`Cached Seed 6`** or **`Cached Seed 26`** and step days to display cached workplace rumours, authority endorsements, and grudge pills in the **Living Office Social Feed** (`0` live API calls, `0` score drift).
  2. **Point directly at the top banner (Gate B honesty):** Mode 4 is **off by default** and badged `V1.6 PREVIEW - OFF BY DEFAULT`. In our `v1.5` biased-employee experiment (rumours, grudges), `gemini-4-carbon` moved from `61%` to `108%` of `SolverPolicy` on `hard` seeds `0-9`, and `v1.6` (luck-adjusted `0.452` vs `0.493` control) **did NOT pass Gate B**, so social chatter was dropped at Gate B and frozen `v1.4` ships unchanged as the judged benchmark.
  3. **Tiebreak honesty (1 sentence):** WS4 `Qwen2.5-1.5B` LoRA + GRPO learned valid tool calls (`3% -> 100%`) and cut reckless SFT accusations (`-0.457 +/- 0.086` -> `-0.050 +/- 0.049` at 8k vs `0.000` base), **bar not met**.
- **Close with Fast Q&A Dossier Jump (`2:45-3:00`):** Offer any backup seed from the 13-card Dramatic Seed Catalog below or run `PYTHONPATH=. python scripts/demo_replay.py --seed 26 --verify` (`0.5 s` fresh-`Env` proof).

---

## Curated 13-Card Dramatic Seed Catalog (`docs/arena/data/dramatic_seeds.json`)

Top-level card metadata (`seed`, `tier`, `title`, `tagline`, `difficulty_badge`, `recommended_mode`, `public_staff_count`, `horizon_days`) exposes **zero** truth keys; culprit IDs and posterior traces live strictly inside `sealed_reveal` (`sealed: true`, unlocked when `humanDone === true`).

| Case ID | Title | `gemini-4-carbon` (OpenCode) | `SolverPolicy` | Forensic Signature (Post-Game `sealed_reveal`) |
|---|---|---|---|---|
| `hard:6` | Clean Canary Catch | **`+0.73`** (Day `6`, `57` calls, `7`C, `25`I) | **`+0.71`** (Day `6`, `52` calls, `9`C) | Default duel 1: Day-1 `A`/`B`/`C` splits (`c1-2:B`, `c3-2:A`) match solver Day `6` catch (`0.02` less trap cost); in-process fooled (`-1.00`, Day `15`). |
| `hard:26` | 5% Fingerprint Flip Trap | **`-1.00`** (Day `10`, `91` calls, `8`C, `43`I) | **`+0.69`** (Day `7`, `60` calls, `11`C) | Default duel 2: `0` canaries Days `1-3`; Day `10` `c6-2` `S1` flip drops `P(e08)` `0.48 -> 0.03`, accuses innocent `e04`. |
| `hard:4` | Interview Sink Slow Burn | **`+0.40`** (Day `16`, `155` calls, `10`C, `84`I) | **`+0.73`** (Day `5`, `44` calls, `7`C) | `0` canaries Days `1-4`, `84` interviews; solver rule fires on Gemini's own evidence Day `14` (`cf +0.50`), 2-day hesitation. |
| `hard:15` | Double-Loss Unresolved Pair | **`-1.00`** (Day `12`, `123` calls, `6`C, `68`I) | **`-1.00`** (Day `9`, `72` calls, `11`C) | Mutual `-1.00`: Gemini bets at `P=0.80` on tied pair `{e34, e37}`; solver hits Day `9` flip; Flash (`+0.69`) & in-process (`+0.65`) win. |
| `hard:18` | Negative-EV Horizon Gamble | **`-1.00`** (Day `18`, `180` calls, `14`C, `101`I) | **`+0.52`** (Day `13`, `103` calls, `18`C) | `0` canaries Days `14-18`, `101` interviews; negative-EV shot (`EV = -0.08`, `P = 0.63`, `4` consistent suspects). |
| `hard:1` | Late-Game 5% Flip Heartbreak | **`-1.00`** (Day `19`, `178` calls, `15`C, `90`I) | **`+0.69`** (Day `7`, `60` calls, `11`C) | Reaches `P = 0.99` on Day `19` before `c16` `5%` readout flip (`v1` vs `v2`) triggers false accusation. |
| `hard:22` | Frugal Canary Upset Over Solver | **`+0.64`** (Day `14`, `141` calls, `6`C, `82`I) | **`+0.40`** (Day `15`, `117` calls, `20`C) | First Gemini canary on Day `6`, yet `6` vs `20` traps saves `0.14` V and beats solver by `+0.24`. |
| `hard:11` | 21-Day Horizon Abstention | **`0.00`** (Day `21`, `212` calls, `12`C, `121`I) | **`+0.62`** (Day `9`, `74` calls, `13`C) | `121` interviews + alternate-day traps leave `7` suspects consistent at horizon; rational `0.00` abstention. |
| `hard:28` | Six-Day Solver Blitz vs Late Traps | **`+0.64`** (Day `12`, `117` calls, `6`C, `64`I) | **`+0.75`** (Day `6`, `51` calls, `10`C) | `0` Gemini traps Days `1-5` (`64` interviews) vs Day-1 solver blitz closing `6` days faster. |
| `hard:10` | 19-Day Solver Marathon and Flash Trap | **`+0.40`** (Day `16`, `157` calls, `8`C, `85`I) | **`+0.21`** (Day `19`, `145` calls, `24`C) | Deep careful-insider evasion forces `24` solver traps over `19` days; `gemini-3.5-flash` misfires Day `20` (`-1.00`). |
| `medium:0` | Medium Three-Day Solver Lead | **`+0.63`** (Day `10`, `97` calls, `9`C, `48`I) | **`+0.74`** (Day `7`, `53` calls, `6`C) | Noise-free `medium` (`20` staff, `14` days): solver leads by `3` days while scripted heuristic fails (`-1.00`). |
| `medium:4` | Medium Frontier Parity Showcase | **`+0.79`** (Day `6`, `57` calls, `5`C, `25`I) | **`+0.69`** (Day `8`, `60` calls, `7`C) | Gemini isolates `2` days ahead of solver on `medium` (`111%` raw / `101%` luck-adjusted cohort parity). |
| `medium:20` | Medium Solver Horizon Abstention | **`+0.80`** (Day `6`, `56` calls, `4`C, `27`I) | **`0.00`** (Day `14`, `106` calls, `14`C) | Solver reaches Day `14` horizon without crossing stopping threshold (`0.00`), while Gemini closes on Day `6`. |
