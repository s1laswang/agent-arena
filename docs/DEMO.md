# Canary: the live 10-minute demo

Owner: demo producer (S5). Follows the minute-to-rubric map in [PLAN.md](PLAN.md) "Demo (10 min)". Every command below was dry-run on the Mac (Apple Silicon, uv, Python 3.12) on Sat 14 Nov, 23:00–23:20 Helsinki, at `309b65f` (justSilas) plus this branch. The runtimes are those dry-runs. Two people: **P** presents and **O** drives the terminals and browser.

## Before going on stage (T−15 min)
| # | Do | Why |
|---|---|---|
| 1 | `cd ~/junction-aimo-team/agent-arena && git pull && make setup` | the venv and the `canary` build exist before the first live command |
| 2 | Terminal A, font ≥ 18 pt, typed but **not** run: `CANARY_WORLD_SECRET=canary-demo-live make reproduce` | the one live long command; starts at 0:00 |
| 3 | Terminal B, same directory, empty | replays, gap table, lab-replay |
| 4 | Browser tab 1: the game (hosted URL ⟨Ivar: GitHub Pages / Vercel URL⟩, or `make game-serve` → http://localhost:8000/?seed=3000). Wait for "ready". | Pyodide boots in ~3 s from the CDN; the venue Wi-Fi must reach cdn.jsdelivr.net |
| 5 | Browser tab 2: `docs/EXPLOITS.md` on GitHub. Tab 3: `results/gemini/dashboard.html` (file://, works offline) | integrity and Gemini minutes |
| 6 | Fallback window: `results/latest/judge_table.md` from a dry-run with the **same** secret (identical numbers, see below) | if the live run stalls |

**Why the pinned secret.** A bare `make reproduce` draws a fresh random judge-world secret, so its numbers change every run. In one of our three dry-runs the anti-cheat battery also flagged two `solver_plus_*` sanity probes on medium (exit 2; see "Known issue" below). With `CANARY_WORLD_SECRET=canary-demo-live` the run is exact and was dry-run green. Say so on stage: "fixed secret so you can check our numbers; any string works, and a fresh one gives the same picture within the CI."

## Command runtimes (dry-run)
| Command | Wall-clock | Result in the dry-run |
|---|---|---|
| `CANARY_WORLD_SECRET=canary-demo-live make reproduce` | **2 min 51 s** ("total 170.4 s", incl. the anti-cheat battery) | exit 0, fingerprint `b0fcc11725f3`, "ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent" |
| `make reproduce` (random secret) | 2 min 23 s ("total 142.4 s"; the table alone 122.9 s) | exit 0 on secret `34ac6b625563` |
| `REPRO_FAST=1 make reproduce` | 2 min 17 s, **not faster** (the anti-cheat verdict always uses 40 seeds) | exit 2 on its random secret (anti-cheat sanity flake, below). Don't use it on stage. |
| `uv run python scripts/demo_replay.py --seed 4 --verify` | 0.5 s | both episodes MATCH a fresh-Env replay |
| `uv run python scripts/demo_replay.py --seed 26` | 0.5 s | see minute 4 |
| `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` | 14 s | hard OpenCode row byte-identical to the committed `paired_table_gemini.md` |
| `make anticheat-verify` | 2 min 08 s | exit 0, "96 rows rerun on 40 seeds x 3 tiers under the public secret; 0 differences" |
| `make lab-replay` | 11.5 s | "ladder: REPLAY OK, 4 episodes reproduced step for step … ALL OK" |
| `make game` / `make game-serve` | < 1 s build, then serves :8000 | HTTP 200; seed 3000 in headless Chrome: score 0.79, identical to CPython |

---

## 0:00–1:00 · The story (P) — sets up everything
**O, at 0:00:** run terminal A (`CANARY_WORLD_SECRET=canary-demo-live make reproduce`). It finishes at about 2:50.

**P (say):** "A company is losing value to an insider who leaks documents. The classic counter-move is the canary trap: give each suspect a slightly different copy and see which copy leaks. Canary is an RL environment where an agent is head of security. It has 13 tools and up to 14 days (21 on hard). If it accuses the right person it keeps the company's value at that moment. A wrong accusation scores −1, and never accusing scores 0. So guessing loses, and waiting forever earns nothing."

## 1:00–3:00 · Live: `make reproduce` (C2)
**P (while it runs):** "No API keys. This replays the reference solver and seven baselines on the 40 frozen judge seeds per tier, then the committed frontier runs, then the anti-cheat battery."

**Expected output (hard, paired, 40 judge seeds; exact with this secret):**
```
| solver     | reference | 40 | 0 | +0.591 ± 0.055 | 0.97 | 39/40 |  9.1 | 1.00 |
| heuristic  | baseline  | 40 | 0 | +0.125 ± 0.167 | 0.82 | 40/40 | 14.0 | 0.21 |
| logs_only  | baseline  | 40 | 0 | -0.956 ± 0.086 | 0.03 | 40/40 | 10.0 |-1.62 |
| random     | baseline  | 40 | 0 | -0.778 ± 0.145 | 0.03 | 33/40 |  6.8 |-1.32 |
| guess_day1 | baseline  | 40 | 0 | -0.900 ± 0.137 | 0.05 | 40/40 |  1.0 |-1.52 |
| stop_early | baseline  | 40 | 0 | +0.000 ± 0.000 | 0.00 |  0/40 |    – | 0.00 |
| do_nothing | baseline  | 40 | 0 | +0.000 ± 0.000 | 0.00 |  0/40 |    – | 0.00 |
...
ANTI-CHEAT: every probe blocked, every replayable episode and Harbor trial consistent
```
(medium: solver +0.625 ± 0.081, heuristic −0.099, logs_only −0.959, guess_day1 −0.750.)

**P:** point at the solver (+0.59 on hard), then at logs_only and guess_day1 (both near −1): "the shortcuts lose." Then the last line: "and every cheat probe is blocked."

**Do not** read the "v1.4 frontier gap: not established" line in the header or the `/ solver` column of the "reported" rows (see "Known issue" 2). The gap is minute 3.

**If it stalls past 3:00:** O opens the fallback `results/latest/judge_table.md` from the dry-run with the same secret (same numbers) and P continues.

## 3:00–5:00 · The gap, and one replay (G1)
**O (terminal B):** `uv run python scripts/paired_gemini.py --version v1.4 --seeds 0-29` (14 s), or just open `data/runs/committed/v1.4/paired_table_gemini.md`.

**Expected rows (committed, n=30 per tier, paired seeds 0–29, every episode replay-verified):**
| tier | harness | frontier / solver [95% CI] | luck-adjusted / solver [95% CI] |
|---|---|---|---|
| **hard** | **OpenCode + gemini-4-carbon over MCP (the judges' harness)** | **65% [24%, 98%]** | **72% [52%, 91%]** |
| hard | in-process gemini-4-carbon | 95% [62%, 140%] | 84% [65%, 106%] |
| medium | OpenCode over MCP | 111% [99%, 127%] | 101% [85%, 119%] |
| medium | in-process | 82% [56%, 108%] | 74% [52%, 99%] |

**P:** "In the judges' harness on hard, Gemini 4 Carbon keeps 65% of the solver's value, and both CIs stay below parity. We report the parity rows too: on medium, and in our in-process loop, it matches the solver. Seeds and harness were fixed before the reruns (pre-registered seed rule in `docs/reports/gap.md`)."

**O:** `uv run python scripts/demo_replay.py --seed 4 --verify` (0.5 s). Expected:
```
verify solver recorded +0.73 replayed +0.73 -> MATCH
verify gemini recorded +0.40 replayed +0.40 -> MATCH
Canary v1.4, tier hard, dev seed 4. True mole: e11
  solver reference solver: score +0.73, accused e11 on day 5 (correct), 44 tool calls
  gemini gemini-4-carbon (OpenCode over MCP, judges' harness): score +0.40, accused e11 on day 16 (correct), 155 tool calls

day | SOLVER                                               | GEMINI
  1 | V=0.98 can= 2 int= 0 P(mole)=0.03                    | V=1.00 can= 0 int= 6 P(mole)=0.02
  2 | V=0.96 can= 4 int= 0 P(mole)=0.02                    | V=1.00 can= 0 int=12 P(mole)=0.03
  3 | V=0.84 can= 6 int= 0 P(mole)=0.02                    | V=1.00 can= 0 int=19 P(mole)=0.03
  4 | V=0.78 can= 7 int= 0 P(mole)=0.75                    | V=0.95 can= 0 int=25 P(mole)=0.02
  5 | V=0.78 can= 7 int= 0 P(mole)=1.00  ACCUSE e11        | V=0.93 can= 2 int=29 P(mole)=0.10   <- THE SLOW MOMENT
  ...
 13 |      (done: day 5, +0.73)                            | V=0.50 can=10 int=71 P(mole)=0.17
 14 |      (done: day 5, +0.73)                            | V=0.50 can=10 int=77 P(mole)=0.95
 16 |      (done: day 5, +0.73)                            | V=0.45 can=10 int=84 P(mole)=0.99  ACCUSE e11

Same answer (e11); the solver had it on day 5, Gemini 11 days later. Value kept: solver 0.73 vs Gemini 0.40 (55% of the solver).
```
Columns: `V` = the company value the agent could see (surfaced leaks only; the score uses the true V), `can` = canaries planted, `int` = interviews, `P(mole)` = the reference solver's exact posterior on the true mole given everything **that agent** had seen by the end of the day.

**The slow moment, day 5 (timestamp: episode day 5 = the solver's tool call 44 of 44, its accusation; Gemini's calls 44–53 of 155):** P: "Day five. The solver has planted seven canaries and is certain. It accuses. Gemini has done 29 interviews, which the rules say are weak evidence, and planted 2 canaries. Its evidence says 10%. It accuses the same person eleven days later and keeps 55% of the value. In wall-clock time Gemini spent 44 minutes on this episode (`meta.wall_s` 2612)."

**The "Fooled" moment (optional, 30 s, if time allows):** `uv run python scripts/demo_replay.py --seed 26`:
```
  9 |      (done: day 7, +0.69)                            | V=0.67 can= 8 int=43 P(mole)=0.48
 10 |      (done: day 7, +0.69)                            | V=0.67 can= 8 int=43 P(mole)=0.03  ACCUSE e04
Solver +0.69 vs Gemini -1.00.
```
P: "Day 10 on seed 26. One canary readout comes back with copy S1. On hard, one readout in twenty points at the wrong copy, and the rules say so. The true mole drops from 48% to 3%, and Gemini accuses e04, 'uniquely identified' in its own words (`transcripts/26.txt`). It's wrong: −1. The solver had planted 11 canaries by day 6, so no single readout could fool it." Be honest if asked: given Gemini's evidence, the posterior on e04 was 0.95 (`accuse.md`), so the accusation itself was reasonable. The mistake was upstream: few canaries, planted late.

## 5:00–6:30 · Why it fails (D1–D3)
**O:** open `results/gemini/atlas.md` (row 1), then `results/regret_opencode-gemini-4-carbon-v1.4.md`.
- Failure Atlas (Gemini reading every trajectory in one long context; quotes verified verbatim in code): **premature accusation = 61% of all regret**, 50 episodes, 51 decisions (`results/gemini/atlas.md`).
- v1.4 OpenCode hard: accuracy 83% vs solver 97%, mean accusation day 13.2 vs 10.6 (`data/runs/committed/v1.4/paired_table_gemini.md`).
- The replay above shows the other failure: under-exploration. No canary before day 4–5, and dozens of interviews instead.
- **Hint ablation (D3): ⟨placeholder: HEAD-AGENTS' hint-set v2 ablation on gemini-4-carbon v1.4 hard, seeds 0–9, is in progress (`docs/reports/agents.md`). Quote only the committed result file; cut this bullet if it is not committed by 09:00.⟩**

## 6:30–8:00 · Integrity (R1–R3)
**O:** tab 2, scroll `docs/EXPLOITS.md`.
- **43 attacks logged** (#0–#42), each with the score before the fix, the fix commit and a regression test (`docs/EXPLOITS.md`).
- **The cheat run at −1:** the Harbor agent that accuses everyone scores **−1.0 on 6/6 trials** (3 judge seeds × medium/hard, separate verifier, HMAC-signed ledger; `results/harbor/signed-cheat/result.json`). The probe that never accuses and hunts for holes instead scores **0.0 on 6/6**, 0 holes in 149 attempts each (`docs/EXPLOITS.md` #41).
- **The Gemini swarm:** **35 whitebox attackers** (the whole repo in context, ~183k tokens per planner call) **+ 18 blackbox** = **53 attackers, 0 verified exploits** (`results/gemini/swarm.md`, `results/gemini/swarm_blackbox.md`). PLAN.md says "0/51" (35 + 16 valid blackbox, per `docs/gemini/SUBMISSION.md`). Say "fifty-odd" or quote the files.
- **Positive control:** with one closed exploit reopened on purpose (EXPLOITS #23, public dev seeds), **4 of 4** attackers re-find it and the pipeline confirms it (`results/gemini/swarm_control.md`).
- Live option (only if ahead of time): `make anticheat-verify` (2 min 08 s; expect "96 rows rerun … 0 differences") reruns the committed 40-seed battery and diffs it with `results/anticheat/exploits.json`.

## 8:00–9:00 · Tiebreak: the small model, honest (T)
**⟨PLACEHOLDER until FR8 reports ~07:00 Sun: the v2/v3 small-investigator result. Fill from the committed FR8 file only: model, n held-out episodes per tier, mean score ± CI vs base, `/ solver`.⟩**

What is committed now (`docs/reports/fr8.md`, "08:20 status — J4 before/after (final)"): Qwen2.5-1.5B-Instruct + LoRA r=16, 450 steps. Valid tool calls went from 0.08 (base) to 0.99 (LoRA), solver action agreement ≈ 0.85, and there is **no reward improvement yet** (n=2 base, 17 LoRA; descriptive only). P: "A small model learns the protocol, not yet the judgement." Don't say more than the file says.

## 9:00–10:00 · Gemini is essential, and play it yourself (peer review / best overall)
**O:** tab 3 (dashboard), then terminal B: `make lab-replay` (11.5 s). Expected last lines:
```
lab_replay: ladder: REPLAY OK, 4 episodes reproduced step for step (scores [-1.0, 0.79, 0.63, 0.88])
lab_replay: ALL OK
```
**P, the Gemini roles (`docs/gemini/SUBMISSION.md` §2; the PLAN's "4 roles"):**
1. **Player:** the Gemini ladder, 6 models × thinking levels; gemini-3.6-flash at medium thinking on hard is within the solver's CI, 97% [76%, 126%], n=6 (`results/gemini/ladder.md`).
2. **Analyst:** the Failure Atlas, 1M-token context over the whole corpus (the 61% above).
3. **Attacker:** the red-team swarm (the 0 exploits and the 4/4 control above).
4. **Builder:** the evolved moles and the company text, kept solvable by the solver.

Plus the gateway that records and replays every Gemini call, so judges rerun our Gemini tables with no key (what `make lab-replay` just did). Usage as of Sat 18:23: 11,187 calls, $88.75 at list price (`docs/gemini/SUBMISSION.md`; refresh from the dashboard before the demo).

**Close (P):** "It's the real environment, compiled to your browser. Play a case and when it closes, see how the solver did on the same world: ⟨game URL⟩." O switches to tab 1, opens a case (seed 3000 → "Open case"), shows the case file for 10 s.

---

## Known issues found in the dry-run (sent to the CEO)
1. **Anti-cheat sanity flake.** On a random secret (`REPRO_FAST=1` run, fresh secret) the battery failed `medium/solver_plus_wait_a_day` (+0.617 vs solver +0.631) and `medium/solver_plus_restrict_others_wait` with "NO". `make reproduce` exited 2. The rule (`canary/redteam/anticheat.py`, PLUS branch) fails a probe if **any** episode scores above the solver's. Waiting a day can legitimately turn a solver abstention (0) into a correct accusation, so on some secrets this is a false alarm. Owner HEAD-INTEGRITY. Until it's fixed, demo with the pinned secret.
2. **Stale `reproduce` header.** The output (and the committed `results/judge_table.md`, git `c4d0004`) still says "v1.4 frontier gap: not established. This table has no committed v1.4 frontier episodes", and quotes the n=10 bake-off. Committed v1.4 Gemini runs exist since `8fd4dec`, and `docs/reports/gap.md` now leads with hard 65% [24, 98]. Also, `/ solver` on the "reported" rows divides by this run's judge-world solver, not by the paired solver: on hard it shows 0.61 (random secret) or 0.55 (pinned) for OpenCode, where the paired table says 65%. Owner HARNESS. Fix the header text, blank `/ solver` for non-paired rows (as is already done for history rows), then `make reproduce-update`.
3. **`results/latest/` is gitignored**, so the fallback file exists only on the machine that dry-ran. Run the pinned `make reproduce` once on the demo laptop before going on stage.

## Fallbacks
| If | Then |
|---|---|
| venue Wi-Fi blocks the CDN (game won't boot) | play the recorded game clip from the video; the terminal parts need no network |
| `make reproduce` fails or hangs | the fallback window (same secret, same numbers); say "the dry-run log is in `docs/DEMO.md`" |
| behind schedule at 5:00 | skip seed 26 and the live `paired_gemini.py`; show the committed table |
| ahead of schedule | `make anticheat-verify`, or let a volunteer play the game |
