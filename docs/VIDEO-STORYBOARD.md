# Canary: video storyboard (≤ 10 min, peer review / best overall)

Owner: demo producer (S5). Target length **8:40**, which leaves 80 s of slack under the 10-minute cap. Format: 1080p screen recording plus voice-over.

**Source.** Ivar's `docs/VIDEO-SCRIPT.md` (branch `ivar/aq-game-ux`) was **not on GitHub** at 23:20 Sat (no branch, no PR, no file on disk). This storyboard therefore follows the arc of the live demo (`docs/DEMO.md`, which maps to `docs/PLAN.md` "Demo (10 min)"). When Ivar pushes his script, merge his wording and shots into the scenes below and keep the number rules.

**Number rule.** Every number on screen or in the voice-over is copied from a committed file and tagged `[src: path]`. The `[src]` tags are for editors and never appear on screen. A number without a tag is not allowed in the cut. Placeholders are written `⟨…⟩` and must be filled from a committed file or cut before export.

**Voice-over.** Each `VO[id]` line is one clip. `scripts/video_vo.py` turns them into `docs/video/vo/<id>.mp3` with ElevenLabs (key in a local `.env`, never committed); the clips with a placeholder are skipped. Re-run the script after any wording change.

**Generated (Sat 23:17, voice "George", `eleven_multilingual_v2`), clip lengths:** 01-hook 19.9 s · 02-env 22.8 s · 03-bar 20.7 s · 04-gap 27.2 s · 05-replay 27.4 s · 06-fooled 25.2 s · 07-why 17.1 s · 08-integrity 29.3 s · 10-close 17.7 s = **3 min 27 s of voice**; 09-small pending. Each scene's slot is longer than its clip; fill the rest with the screen action described.

---

## Scene 1 · 0:00–0:40 · The mole (hook)
**Shot:** the browser game, case-file UI, seed 3000. Slow scroll over the staff list, then the leak feed with one leaked document.
**On screen:** "Somebody inside is leaking. Every day you wait, the company loses value."

> VO[01-hook]: Somebody inside the company is leaking documents, and every day you don't catch them the company loses value. You're the head of security. You can hand out marked copies of a document, a canary trap, and watch which copy leaks. Accuse the right person and you keep what's left. Accuse the wrong one and you lose everything.

## Scene 2 · 0:40–1:30 · What Canary is
**Shot:** the rules dialog in the game (the page shows the env's own `instruction()` text), then the 13 tools in the tool panel.
**On screen:** "13 tools · 14 days (hard 21) · score = value left if right, −1 if wrong, 0 if you never accuse"

> VO[02-env]: Canary is a reinforcement-learning environment for agents. The agent gets thirteen tools: staff lists, documents, access logs, interviews, and canary traps. The score is the company's value at the accusation if it's right, minus one if it's wrong, and zero if it never accuses. So guessing has negative expected value, and so does waiting forever.

Numbers: 13 tools `[src: canary/env.py tools_spec(); docs/reports/gap.md "The prompts and the 13 tools"]`; −1 / 0 scoring `[src: results/judge_table.md header "reward:"]`.

## Scene 3 · 1:30–2:30 · The bar: a solver, and the baselines that fail
**Shot:** terminal, `make reproduce` scrolling, then freeze on the hard paired table. Highlight the solver row, then the baselines.
**On screen (hard, 40 judge seeds):** solver **+0.547**, heuristic **−0.044**, logs-only **−1.000**, random **−0.754**, guess on day 1 **−0.950**, do nothing **0.000** `[src: results/judge_table.md, "## hard (headline)" paired rows]`

> VO[03-bar]: A Bayesian reference solver sets the bar. One command, make reproduce, replays the whole table with no API keys. On the hard tier the solver keeps about half the company's value. The obvious shortcuts lose money: reading the logs alone, guessing on day one, or acting at random all score below zero.

## Scene 4 · 2:30–3:40 · The gap: Gemini in the judges' harness
**Shot:** `data/runs/committed/v1.4/paired_table_gemini.md` rendered as a slide: two bars per tier (solver vs gemini-4-carbon), CI whiskers.
**On screen:**
- hard, OpenCode + gemini-4-carbon over MCP, n=30: **65% of the solver [95% CI 24%, 98%]**; luck-adjusted **72% [52%, 91%]** `[src: data/runs/committed/v1.4/paired_table_gemini.md, hard OpenCode row]`
- accuracy **0.83** vs solver **0.97**; mean accusation day **13.2** vs **10.6** `[src: same file, same rows]`
- footnote: in-process gemini-4-carbon on hard **95% [62%, 140%]** (parity); OpenCode on medium **111% [99%, 127%]** `[src: same file]`

> VO[04-gap]: Then we gave the same task to Gemini 4 Carbon in the judges' own harness, OpenCode over MCP, on thirty hard worlds paired with the solver. It kept sixty-five percent of the solver's value, and the confidence interval stays below parity. It was right less often, and it accused about two and a half days later on average. We report the parity results too: on medium, and in our own in-process loop, Gemini matches the solver.

## Scene 5 · 3:40–5:00 · Replay: same world, same answer, eleven days late
**Shot:** terminal, `python scripts/demo_replay.py --seed 4`. Reveal the day rows one at a time (screen recording of the printed table, cursor moving down). Freeze on day 5.
**On screen:** day 5. Solver: 7 canaries, **P(mole) = 1.00 → accuses e11**. Gemini: **29 interviews, 2 canaries, P(mole) = 0.10**. `[src: data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl seed 4; data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl seed 4; posterior from scripts/demo_replay.py]`
Then fast-forward to day 16: Gemini accuses the same e11. **Score 0.73 vs 0.40 (55%)** `[src: same two episodes, "score"]`

> VO[05-replay]: Here's one hard world, played by both. The solver spends its first four days planting canaries. By day five the leaks have named the mole, and it accuses. Gemini spends those same days interviewing people: twenty-nine interviews and two canaries. Interviews are weak evidence, and the rules say so. It finds the same person, eleven days later, and by then the company has lost almost half of what the solver saved.

## Scene 6 · 5:00–5:50 · Fooled: one noisy readout
**Shot:** `python scripts/demo_replay.py --seed 26`, freeze on days 9–10; overlay Gemini's own final message from `data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/transcripts/26.txt` ("Their intersection uniquely identified e04").
**On screen:** day 9 **P(true mole e08) = 0.48** → day 10 canary readout `S1` → **P = 0.03**, Gemini accuses **e04: −1.00**. Solver: 11 canaries by day 6, accuses **e08 on day 7: +0.69** `[src: the seed-26 rows of the same two episodes.jsonl files; posterior from scripts/demo_replay.py]`. Hard tier fingerprint accuracy **0.95** `[src: canary/rules.py "fingerprint_accuracy=0.95"]`

> VO[06-fooled]: On another world Gemini is fooled. The hard tier tells the agent that one canary readout in twenty points at the wrong copy. Gemini planted its first canary on day four and relied on a single late readout. That readout was wrong, and Gemini called its suspect, quote, uniquely identified. It was the wrong person. The solver had planted eleven canaries by day six, so no single readout could mislead it.

## Scene 7 · 5:50–6:40 · Why agents fail, across every run
**Shot:** `results/gemini/atlas.md` top table, then one atlas belief-vs-solver chart from `results/gemini/atlas_charts/`.
**On screen:** premature accusation = **61% of all regret** across GPT, Grok and Gemini agents, **50 episodes** `[src: results/gemini/atlas.md, row 1 "Premature Accusation on Sub-Threshold Posterior"]`
**Placeholder:** hint ablation on gemini-4-carbon, v1.4 hard ⟨arm → score, from the committed ablation file when HEAD-AGENTS commits it; cut the line if not committed⟩

> VO[07-why]: Gemini also reads every trajectory we have in one long context and names the failure modes, with quotes that are checked word for word in code. The biggest one, across every agent family, is accusing before the evidence is in: sixty-one percent of all lost value.

## Scene 8 · 6:40–7:50 · Can you cheat it?
**Shot:** scroll `docs/EXPLOITS.md` on GitHub (fast), then the Harbor cheat result, then `results/gemini/swarm.md` scoreboard.
**On screen:**
- **43 attacks logged**, each with its fix and a regression test `[src: docs/EXPLOITS.md, rows #0–#42]`
- Harbor reward-hack agent that accuses everyone: **−1.0 on 6/6 trials** `[src: results/harbor/signed-cheat/result.json "mean": -1.0]`; the probe that never accuses: **0.0 on 6/6** `[src: docs/EXPLOITS.md row #41]`
- Gemini red-team swarm: **35 whitebox + 18 blackbox attackers, 0 verified exploits** `[src: results/gemini/swarm.md "Verified exploits: 0"; results/gemini/swarm_blackbox.md "Verified exploits: 0"]`
- positive control: **4 of 4** attackers re-find a deliberately reopened exploit `[src: results/gemini/swarm_control.md "Verified exploits: 4"]`

> VO[08-integrity]: A benchmark is only worth something if you can't game it. We logged every attack we tried on our own reward, forty-three of them, each with a fix and a regression test. A Harbor agent that accuses everyone scores minus one on every trial. Then we let Gemini attack it: fifty-three attackers, most of them reading the entire codebase. Zero verified exploits. To prove the detector works, we reopened one old hole on purpose, and four out of four attackers found it.

## Scene 9 · 7:50–8:10 · Small models (tiebreak)
**Shot:** a two-row table, then the training curve if FR8 commits one.
**On screen (now):** Qwen2.5-1.5B + LoRA: valid tool calls **0.08 → 0.99**; **no reward gain yet** `[src: docs/reports/fr8.md "## 08:20 status — J4 before/after (final)"]`
**Placeholder:** ⟨v2/v3 result, FR8 report ~07:00 Sun: model, n, score ± CI vs base, file path⟩. If the v3 result shows no reward gain, keep the honest line.

> VO[09-small]: ⟨placeholder until the FR8 report: one sentence, the committed v3 number, or "a small model learns the protocol but not yet the judgement"⟩

## Scene 10 · 8:10–8:40 · Gemini runs the lab, and you can play it
**Shot:** `results/gemini/dashboard.html` (usage panel), then `make lab-replay` ending in "ALL OK", then the game's "case closed" reveal comparing the player with the solver.
**On screen:**
- Gemini roles: player (ladder) · analyst (atlas) · attacker (swarm) · builder · gateway `[src: docs/gemini/SUBMISSION.md §2]`
- **11,187 Gemini calls, $88.75** at list price, as of Sat 18:23 `[src: docs/gemini/SUBMISSION.md §2; refresh from results/gemini/dashboard.html before export]`
- `make lab-replay`: **4 episodes reproduced step for step, no key** `[src: make lab-replay output; recorded store results/gemini/replay-ladder/]`
- "Beat the solver: ⟨game URL⟩"

> VO[10-close]: Gemini plays the game, explains the failures and attacks the reward, and every Gemini number replays offline without a key. Now it's your turn. The game runs the real environment in your browser, and when the case closes it shows you how the solver did on the same world. Can you beat it?

---

## Shot list and assets
| Scene | Asset | How to capture | Status |
|---|---|---|---|
| 1, 2, 10 | browser game, seed 3000 | `make game-serve`, open http://localhost:8000/?seed=3000 | ready (dry-run 23:10 Sat) |
| 3 | terminal `make reproduce` | record live; 2 min 23 s on the Mac, cut to 20 s | ready |
| 4 | gap bar chart | from `data/runs/committed/v1.4/paired_table_gemini.json` | to make (slide) |
| 5, 6 | terminal `scripts/demo_replay.py --seed 4` / `--seed 26` | record live, 0.5 s per run | ready |
| 6 | Gemini's final message, seed 26 | `transcripts/26.txt`, last `"type":"text"` line | ready |
| 7 | atlas table and chart | `results/gemini/atlas.md`, `results/gemini/atlas_charts/` | ready |
| 8 | EXPLOITS, Harbor, swarm | GitHub file view; `results/harbor/signed-cheat/result.json`; `results/gemini/swarm.md` | ready |
| 9 | small-model table | FR8 report | **placeholder** |
| 10 | dashboard + lab-replay | `results/gemini/dashboard.html`; `make lab-replay` (11.5 s) | ready |

## Do not say
- "Gemini is below the solver" without "in the judges' harness on hard". In-process and on medium it is at parity (Scene 4 footnote).
- Any number from a fresh `make reproduce` run: each run draws a new secret, so its numbers move. Quote `results/judge_table.md` (Scene 3) or the paired v1.4 table (Scene 4).
- That the small model "learned the task" unless the committed v3 file shows a reward gain with a CI above 0.
