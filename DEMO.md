# Canary: 3-Minute Peer-Review Click Script (10:45-12:45)
Note: `DEMO.md` is the 3-minute `10:45-12:45` table/laptop peer-review click script, while [docs/DEMO.md](docs/DEMO.md) is Silas's S5 10-minute finalist stage script.

## Pre-Open Laptop Setup (T-5 min, Keyless, Offline-Ready)

Open four browser tabs and one terminal at the repo root before the `10:45` peer-review rotation starts. Zero API keys are needed.

| Surface | What to Pre-Open | Mode / Latency | Purpose |
|---|---|---|---|
| **Tab 1** | `make game-serve` -> `http://localhost:8000/?seed=3000` (wait ~3 s until status reads `ready`) | Local HTTP + Pyodide | Live playable `canary` Python environment in the browser (`game/site`, built from [game/index.html](game/index.html) and [game/canary_game.py](game/canary_game.py)) |
| **Tab 2** | `docs/demo/replay.html` (`file://`) | 100% offline static HTML | Side-by-side office replay of committed `v1.4` hard episodes (**Seed 6 Caught** and **Seed 26 Fooled**) |
| **Tab 3** | `docs/demo/living_office_v16.html` (`file://`) | 100% offline static HTML | Multi-day gossip, grudge, and rumour replay (`Day 1` -> `Day 7` -> `Day 14`) with explicit off-by-default Gate B banner |
| **Tab 4** | `docs/demo/canary_demo.mp4` | 60-90 s local MP4 | Instant offline fallback video if venue Wi-Fi blocks the Pyodide CDN (`cdn.jsdelivr.net`) |
| **Terminal** | `uv run python scripts/demo_replay.py --seed 26 --verify` | `0.5 s`, keyless | Fresh-`Env` deterministic replay verification of committed episodes ([scripts/demo_replay.py](scripts/demo_replay.py)) |

---

## Minute-by-Minute Script (`0:00` to `3:00`)

### `0:00-0:45` | Hook + Live Browser Game (Tab 1, `?seed=3000`)

- **Say (`0:00-0:10`):** "One of twenty employees is leaking company documents to a rival. Every leak drains company value `V` from `1.00`, and leaks surface 1 to 3 days late. You are head of security: plant watermarked canary traps, watch which variant leaks, and accuse at most once. Right scores the true `V` left, wrong scores `-1`, and never accusing scores `0`."
- **Click sequence (`0:10-0:35` on `http://localhost:8000/?seed=3000`):**
  1. Click **`Open the case file`** (public dev seed `3000`, `medium` tier, 20 staff, 14 days, 8 actions/day, 300 tool calls; on this world `SolverPolicy` catches the mole on Day 6 in 48 calls for `+0.79`, kept sealed until the case closes).
  2. **`EMP`** (`Staff list`, active on open) -> click **`Run staff list`** (free, 0 actions) to load all 20 employees (`e00`..`e19`) into the roster.
  3. Click **`DOC`** (`Documents`) -> click **`Run documents`** (free, 0 actions) to show Day 1's 4 sensitive documents (`d1-1`..`d1-4`, 12 recipients each).
  4. Click **`CAN`** (`Canary`) -> click **`Even split`** (assigns variants `A`, `B`, `C` across the 20 staff), type `Q3 board memo`, and click **`Run canary`** (spends 1 of 8 daily actions to plant `c1`).
  5. Click **`ACC`** (`Accuse`) -> click **`Accuse...`** to open the accusation dialog: drag the **`Your certainty`** slider (`50%` -> `5%` -> `50%`) to show the live decision math: **`Break-even`** certainty is `50.0%` at `V = 1.00` (`1 / (1 + V)`), **`Expected score`** is `p * V - (1 - p)` (`-0.90` on a Day 1 `5%` guess), wrong = **`-1`**, never accuse = **`0`**. Click **`Keep investigating`**.
- **Reviewer click (`0:35-0:45`):** Hand the mouse to the reviewer for **1 click** (`DAY` to close Day 1, `FED` to check the leak feed, or `Agent view [J]` to show the exact MCP JSON reply an AI agent receives).

---

### `0:45-1:45` | Measured Gap, Rehearsal Honesty + Office Replay (Tab 2, `docs/demo/replay.html`)

- **State the measured `v1.4` `hard` picture plainly (`0:45-1:00`, sources: [README.md](README.md), [docs/SUBMISSION.md](docs/SUBMISSION.md), [docs/reports/gap.md](docs/reports/gap.md), [data/runs/committed/v1.4/paired_table_gemini.md](data/runs/committed/v1.4/paired_table_gemini.md), and [results/harbor/rehearsal/TABLE.md](results/harbor/rehearsal/TABLE.md)):**
  - **MCP-only `gemini-4-carbon` headline (`OpenCode`, 13 MCP tools only, dev seeds `0-29`, post-hoc lock `671ed96` committed 28 s after `8fd4dec`):** **`65% [24%, 98%]`** raw and **`72% [52%, 91%]`** luck-adjusted (`+0.322 +/- 0.199` vs `SolverPolicy` `+0.499 +/- 0.119`, `n=30`, every episode replay-verified; `medium` OpenCode `111% [99%, 127%]` raw / `101% [85%, 119%]` luck-adjusted, `hard` in-process `95% [62%, 140%]` raw / `84% [65%, 106%]` luck-adjusted).
  - **Harbor judge-path rehearsal (full container with shell on tag `afterquery-final` `1bc3e281`, [results/harbor/rehearsal/TABLE.md](results/harbor/rehearsal/TABLE.md)):** the MCP-only gap **did not reproduce**; across 3 runs x 10 hard judge tasks, `gemini-4-carbon` scored **`+0.472` (`10` valid), `+0.585` (`10` valid), and `+0.626` (run 3: `9` valid trials, `5` finished after the `08:30` cut-off, `1` infra-excluded)** = **`93%`, `116%`, and `131%`** of the **`+0.506`** oracle (`28/29` valid Gemini accusations correct; note `153%` / `+0.656` was only the `7`-trial `08:52` snapshot before run 3 finished).
  - **Second frontier family (`gpt-5.5`, OpenCode over MCP, pre-registered at `cf394894`):** matches the solver at **`101% [79%, 140%]`** raw (`+0.504 +/- 0.064`, luck-adjusted `84% [67%, 103%]`, `n=30`, paired on the same `0-29` post-hoc lock `671ed96` seeds; `28/28` accusations correct, `17.2` canaries and `4.2` interviews/ep vs Gemini's `8.5` canaries and `68.0` interviews/ep in [results/behaviour_compare_v1.4.md](results/behaviour_compare_v1.4.md)).
- **Click `Seed 6 Caught` (`1:00-1:15`):**
  - True mole **`e34`** (Sofia Niemi, Research).
  - **`gemini-4-carbon` scores `+0.73` on Day 6 in `57` calls** (`7` canaries, `25` interviews; orthogonal hits `c1-2:B` and `c3-2:A`) vs **`SolverPolicy` `+0.71` on Day 6 in `52` calls** (`9` canaries, `0` interviews; `0.02` extra canary cost). When Gemini plants canaries on Day 1, it matches the solver.
- **Click `Seed 26 Fooled` (`1:15-1:45`):**
  - True mole **`e08`** (Nea Nieminen, Research).
  - **`gemini-4-carbon` plants `0` canaries on Days 1-3** while spending **`43` interviews** across the run (`8` canaries total, `91` calls).
  - Day 8 canary `c6` (`D1 = {e04, e08, e37}`) lifts `P(e08)` to **`0.48`** by Day 9. On **Day 10**, `c6-2` hits the **`1-in-20` (`5%`) noisy readout** on `hard` (`fingerprint_accuracy = 0.95`) and reports copy **`S1`** (`{e04, e20, e28}`).
  - Exact posterior `P(e08)` drops **`0.48 -> 0.03`**, and Gemini accuses innocent **`e04`** ("uniquely identified" in [data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/transcripts/26.txt](data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/transcripts/26.txt)) for **`-1.00`**, whereas **`SolverPolicy` scores `+0.69` on Day 7** (`60` calls) with **`11` canaries** planted from Day 1 so no single noisy flip can fool it.

---

### `1:45-2:30` | Anti-Cheat Integrity + Honest Negative Results (Tab 3, `docs/demo/living_office_v16.html`)

- **Integrity (`1:45-2:00`, 15 s):**
  - **`do_nothing = stop_early = 0.000`** on all 40 judge seeds and `10/10` Harbor rehearsal tasks (`guess_day1` averages `-0.95` on `hard`; [results/judge_table.md](results/judge_table.md)).
  - **52 attacks logged and guarded by regression tests** (`#0` to `#51` in [docs/EXPLOITS.md](docs/EXPLOITS.md), plus a `1,034`-attack Gemini red-team sweep on `afterquery-final` with `0` verified exploits in [results/redteam_1000/summary.md](results/redteam_1000/summary.md) and `12/12` judge-protocol checks in [docs/reports/integrity.md](docs/reports/integrity.md)).
  - **`make reproduce` runs keyless** (~1 min): replays committed runs, executes the 40-seed anti-cheat battery, and recomputes the locked `n=30` `HEADLINE`.
- **Living Office `v1.6` Preview + Honest Negative Results (`2:00-2:30`, 30 s):**
  - Switch to Tab 3 (`docs/demo/living_office_v16.html`) and click **`Day 1` -> `Day 7` -> `Day 14`** to show workplace gossip, grudges, and rumours carrying across days.
  - **Point at the top banner (honest Gate B disclosure):** `v1.6` Living Office is an **off-by-default preview** that **did NOT pass the Gate B gap gate** (`v1.5` biased employees moved `gemini-4-carbon` from `61%` to `108%` of `SolverPolicy` on `hard` seeds `0-9`, so it was dropped at Gate B and never shipped into `v1.4`; [docs/reports/gap.md](docs/reports/gap.md)).
  - **WS4 `1.5B` tiebreak + DAgger (honest null, [docs/reports/fr8.md](docs/reports/fr8.md) and [README.md](README.md)):** Qwen2.5-1.5B + LoRA + GRPO learned valid tool syntax (`3% -> 100%`) and cut reckless SFT accusations (`-0.457 +/- 0.086` -> **`-0.050 +/- 0.049` at 8k**, `n=90`, vs **`0.000` base**, `n=36`), and **DAgger round 1** ended at **`-0.542 +/- 0.214` at 8k** (`n=50`, partial): **bar not met** across all seven trained runs + DAgger (none beat `0.000` with CI excluding `0`).

---

### `2:30-3:00` | Fast-Click Q&A Map + Offline Fallback (`docs/demo/canary_demo.mp4`)

Ask *"Which part would you like to inspect?"* and jump in one click:

| Reviewer Question | Instant Click / Command | Verified Fact to Point At |
|---|---|---|
| **"Prove Seed 26 was not cherry-picked or edited."** | Terminal: press Enter on `uv run python scripts/demo_replay.py --seed 26 --verify` (`0.5 s`) | Replays both committed trajectories through a fresh `Env`: `solver +0.69 -> MATCH`, `gemini -1.00 -> MATCH` (`P(e08): 0.48 -> 0.03` on Day 10) |
| **"Why does Gemini lose value when rules are public?"** | Open [results/behaviour_compare_v1.4.md](results/behaviour_compare_v1.4.md), [docs/reports/failure_analysis_v1.4.md](docs/reports/failure_analysis_v1.4.md), or [results/gemini/atlas.md](results/gemini/atlas.md) | `68.0` interviews/ep (`LR = 1.2`) crowd out `plant_canary` (`8.5` vs `gpt-5.5` `17.2` and solver `14.1`); premature accusation drives `61%` of regret |
| **"How is Harbor isolated from container cheats?"** | Open [harbor/README.md](harbor/README.md) and [docs/EXPLOITS.md](docs/EXPLOITS.md) | Separate MCP sidecar (`environment_mode = "separate"`), `0600` consumed world salt, HMAC-signed ledger; `cheat.py` scores `-1.0` on `6/6` trials, `cheat_probe` `0.0` on `6/6` |
| **"What if venue Wi-Fi blocks Pyodide CDN?"** | Switch to **Tab 4** (`docs/demo/canary_demo.mp4`, 60-90 s) | Full recorded browser + replay capture plays locally; Tabs 2-3 (`file://`) and Terminal (`scripts/demo_replay.py`) need zero network |
| **"Where is the full submission & rubric index?"** | Open [docs/SUBMISSION.md](docs/SUBMISSION.md) and [README.md](README.md) | Final rehearsal (`93%` / `116%` / `131%` of `+0.506` oracle), `gpt-5.5` (`101% [79%, 140%]`), post-hoc lock (`671ed96`), `n=32` extension note (`75% [56%, 93%]` luck-adjusted), and one-command judge checks |
