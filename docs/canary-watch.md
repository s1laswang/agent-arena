# Canary watch log

Rule: read only. Never merge or copy Silas's code into our branches. Sources: `git log`/`git show origin/<branch>` on origin justSilas*, vaishnav/*.

## Tick 1, 2026-11-14 ~12:40 Helsinki (baseline)

Last-seen SHAs (tip, commit time +0200):
- justSilas 8970ead 12:33 (was f56cc1d at bake-off 2)
- justSilas-harness / harness2 11f1b4e 12:32
- justSilas-fr8 9600a62 12:28; fr8-trainer 285735f 12:27
- justSilas-v14 8f87ed1 12:08 (rules frozen v1.4)
- justSilas-measure 11fe514 11:25; integrity 013cf9f 08:19; fr8-analyst 54f5544 07:15
- justSilas-grok-bakeoff2 3f91fe4; vaishnav/poisoned-inbox 9068b16 08:11
- All other justSilas-* branches unchanged since 04:30 or earlier.

What changed since f56cc1d (11 commits, `git log f56cc1d..origin/justSilas`):
- `canary/reproduce.py`: invalid (infra) episodes dropped from reported means, per-seed dedupe, newest run wins. Fixes bake-off risk 2. Results refreshed (`results/judge_table.md`).
- Codex smoke run moved to `superseded/` (it double-counted hard seed 0).
- fr8 trainer: `eval_hf` KV/prefix reuse, `--max-calls`, `fr8/j4_eval.sbatch` (fast small-model eval).
- New brief `docs/agents/NEXT-LEVEL.md` (CEO, Sat ~12:30), the plan for the rest of the hackathon.

Numbers (all theirs, from `docs/reports/gap.md` and NEXT-LEVEL.md):
- Codex gpt-5.5 over MCP, v1.3: medium n=11 55% of solver [-8,104], hard n=11 106% [91,136]. No gap on hard.
- Nothing newer yet. Gemini measurement (`gemini-4-carbon`, branch `justSilas-gemini`, OpenCode over MCP and in-process, v1.3 and v1.4) is running but not on origin yet.
- Nothing beats our numbers: we have no frontier run either.

Their plan (what to expect next):
- OpenAI key removed, Gemini unlimited with `gemini-4-carbon`. Rules frozen v1.4 (8f87ed1).
- Thesis: frontier agents never abstain; accuse at P 0.18-0.45 when abstaining (0) beats a likely -1. They want "calibrated commitment" as the measured skill across three families (gpt-5.5, Grok, gemini-4-carbon).
- Skill ladder (`scripts/skill_ladder.py`, n>=400 per tier), copied from Poisoned Inbox.
- v1.5 "dormant mole" knob, branch only.
- Gemini failure analyst, Mole Forge with Gemini mutator, hint ablation (causal), Gemini exploit hunter (black and white box).
- Boot Harbor for real (colima), do-nothing 0 / stop_early about -1 logs in `results/harbor/`; gemini-4-carbon through OpenCode on 3 hard + 3 medium.
- `CANARY_EPISODE_FILE` instead of seed in env; rerun `repro_spread.py 30`.
- Small-model v2 when a V100 frees up (~18:30), goal reward gain.

Ideas to copy (idea only, no code):
- Skill ladder table: one rule removed per rung (lead-reward / lead-demo). We have one-rule ablations in spirit; make it a table.
- Hint ablation: one sentence per failure mode, show tag drops on a real model (lead-lab).
- Report invalid infra episodes as a separate column, never in the mean.
- Run Harbor for real and commit logs (lead-env / lead-harness).

Weaknesses we can beat:
- Their frontier gap is inconclusive (hard 106%) and OpenAI is now removed, so their strongest evidence (Codex) is frozen at n=11. A real, repeated gemini-4-carbon gap on our judge seat would beat it.
- They have not booted Harbor yet (planned). If we boot ours first and commit logs, integrity/craft favour us.
- Their small-model LoRA did not raise reward (n=17, mean -0.148); ours is also unproven. Only a reward gain counts.

Our own gaps this watch exposes (from bake-off 2, still true until fixed): no real frontier run, finance_ap oracle 0.75, shared verifier + chmod 777 /logs, 20 failing tests.

Routing sent: chief, lead-lab (numbers, hint ablation), lead-reward (ladder, integrity), lead-env (Harbor boot, rules freeze), lead-attack (nothing new), lead-demo.

## Tick 2, 2026-11-14 13:16 Helsinki

Last-seen SHAs (changed ones marked *): justSilas* cca3cb8 (was 8970ead), justSilas-harness2* 4c60e11 (was 11f1b4e), justSilas-grok-bakeoff3* 72b32cf (new branch, 10:43 UTC).
Unchanged: harness 11f1b4e, fr8 9600a62, fr8-trainer 285735f, fr8-analyst 54f5544, fr8-ops f7b0124, v14 8f87ed1, measure 11fe514, integrity 013cf9f, agents 51d540b, grok-bakeoff2 3f91fe4, vaishnav/poisoned-inbox 9068b16. Not on origin yet: justSilas-gemini (the gemini-4-carbon runs), env2, agents2, integrity2.

New facts:
- Bake-off 3 (`docs/reports/grok-bakeoff3.md`, run on Canary f56cc1d, Sleeper 07e17ee): Poisoned Inbox 64, Canary 62 (gap 8, difficulty 20, integrity 22, craft 12), Blind Spot 61, The Sleeper 51 (gap 10, difficulty 17, integrity 15, craft 9). Canary fell from 70 to 62 because the official v1.3 Codex run is 1.06x solver on hard and v1.4 hard shows the heuristic at 90% accuracy, +0.196 vs solver +0.516 (they say v1.4 did not restore the collapse). v1.4 has no frontier runs. Its recommendation is still "ship Canary as an unfinished measurement". The judge there did not boot Docker.
- Harbor booted for real (harness2 17ba746, 4c60e11, `results/harbor/`): oracle medium 0.78 / hard 0.66 = in-process solver, do_nothing 0/0, stop_early -1/-1, check_isolation 11/11 OK, 6-task v1.4 build all equal the solver. This closes their bake-off risk 3.
- NEXT-LEVEL.md (cca3cb8): top priority is an anti-cheat port from Poisoned Inbox into Canary: a probe battery inside `make reproduce` (do_nothing, stop_early, random, restrict_all, probe_all, accuse_decoy, malformed args, parallel accuse, calls past cap) plus a control that must keep the solver score, a stop-early ladder (solver cut at 25/50/75% = 0), replay consistency of every committed episode, and a Harbor `ORACLE_POLICY=cheat` run that tries to rewrite reward.txt and hit /ledger and /admin. Vaishnav is the human owner.

Beats us: their Harbor boot with committed logs; their anti-cheat battery will be in the one command. Our equivalents: `make exploits` and docs/EXPLOITS.md, but no Harbor boot logs and shared verifier + chmod 777 /logs.
Beats them: they have no v1.4 frontier run and no Gemini run yet; their frontier gap on v1.3 hard is above the reference. Whoever lands a real, repeated frontier-below-reference number first on the judge seat wins the gap axis.
Ideas to copy (idea only): anti-cheat probe table printed by the one command; stop-early ladder on the reference itself; replay consistency flag; Harbor cheat solution; booting Harbor via colima and committing logs.
Routing: chief, lead-lab, lead-reward, lead-env, lead-harness, lead-demo.

## Tick 3, 2026-11-14 13:54 Helsinki

Last-seen SHAs: justSilas* 5813bb2 (was cca3cb8). All other justSilas*, vaishnav/poisoned-inbox 9068b16 unchanged from tick 2. Still not on origin: justSilas-gemini, justSilas-v15, env2, agents2, integrity2.

New (docs only, 4 files, 189 lines, `git diff cca3cb8 origin/justSilas`): "Plan v3" approved by their CEO after a team brainstorm that included Momin (`docs/IDEAS.md`, `docs/meetings/2026-11-14-mole-company-simulation.md`, NEXT-LEVEL.md additions, CEO log).
- Decision: Canary is the base; Vaishnav's anti-cheat goes in; "Momin's strongest parts go in"; Momin pauses sky GPU jobs so Silas's FR8 can use the GPUs.
- v1.4 frozen (hard: 40 staff, 21 days, 2 canaries/day x 3 variants, leak_damage 0.05, tool cap 420). Confirmation seeds 5000-5799: solver .779/.633/.556, hard accuracy 94.9%; solver minus grok_tactics on hard +.195 (v1.3 was +.233), so v1.4 narrowed the scripted gap. They say only a frontier measurement decides.
- v1.5 candidate "human-bias social layer" (branch justSilas-v15, gated, default off): rumours, grudge pairs, authority-bias accusation, miscommunication forwards, mole action seed_rumour; Gemini writes the chatter. Merge only if the gemini-4-carbon/solver ratio drops vs v1.4 and integrity stays clean.
- RL-trained mole: light MLP on CPU now (reward = solver-relative regret, constraint solver accuracy >= 0.75), GRPO Qwen2.5-0.5B/1.5B mole on V100s later.
- Static Pyodide browser game "beat the AI"; video.
- Gates: A 17:00 (gemini-4-carbon v1.4 n>=20 per tier, v1.5 solver numbers, first RL-mole curve); B 20:00 (ship or drop v1.5, feature freeze).

Read: still no frontier number on v1.4. Their gap bet is v1.5. Our edge only exists if we have a real frontier run below our reference before 17:00-20:00 gates.
Ideas to copy (idea only): rumour/grudge/authority-bias noise stated in the instructions (human-like insiders; fits The Sleeper's chat-request attacks); RL-trained attacker with a catchability constraint (lead-attack, lead-lab); a static browser game for judges.
Open question for the chief: Silas's plan says Momin's parts go into Canary. If the submission is a merged Canary, confirm which of our assets (Sleeper seats, verifier, attacks) are in it, so docs and scorecard target the same artifact.

## Tick 4, 2026-11-14 14:37 Helsinki

Last-seen SHAs: justSilas b4bcd4e (was 5813bb2), harness2 50d8a90, fr8 8b14c4b. New branches: env2 d84fc10, env2-ladder e2f74bb, agents2 65bc46e, integrity2 078a000, v15 f19cc71, v15-bias 5973d92. Still absent: justSilas-gemini. Unchanged: poisoned-inbox 9068b16, measure, v14, others.

Numbers (theirs, `git show 58f25318`, `harbor/README.md` on justSilas):
- **gemini-4-carbon through the judges' path (Harbor + OpenCode over MCP), v1.4, judge seeds 900000-900002, 3 medium + 3 hard, same worlds as the oracle:** oracle mean 0.757, Gemini 0.503 (-0.253); Gemini below the solver on 6/6; medium 900002 Gemini never accused (0). Scores from the server ledger, transcripts kept, 0 keys in the commit. n=6 only. Their Gate A target is n>=20 per tier.
- Pitfall they hit: OpenCode reads only `GOOGLE_GENERATIVE_AI_API_KEY` and Harbor needs `--api-key-name`; otherwise 6 invalid auth zeros (not committed as results).
- Harbor baselines (earlier): oracle 0.78/0.66, do_nothing 0, stop_early -1, isolation 11/11. `make test` 548 passed, 4 skipped (their claim, not re-run by me).
- Skill ladder v1.4 (env2-ladder e2f74bb, results/skill_ladder_v1.4.md, seeds 7000-7399, n=400 per tier): on easy, removing the EV accusation rule costs -0.407 (accuse-last) or -0.178 (accuse at P>=0.5); the other five one-component ablations (careful, delay, single-canary, decoy, framing) show +0.000 on easy. Medium/hard rows not read. Honest read: some rungs do not cost score on easy; they must show cost on hard.

New work, not merged to justSilas yet:
- integrity2 078a000: anti-cheat battery inside `make reproduce` (probes, stop-early ladder, control, replay consistency, grader hardening tests), the Poisoned Inbox port.
- agents2 65bc46e / 75ab74c: RL mole (REINFORCE + catchability constraint), `hard_rl` track, GRPO LLM mole script.
- v15-bias 5973d92: human-bias social layer (rumours, grudges, authority, misforward, seed_rumour), off by default.
- justSilas: Pyodide browser game (WS6) merged (de5e420); FR8 GPU jobs 44410-44412 submitted (WS4).

Beats us: a real frontier run through the exact judge path with a gap on 6/6 (their gap axis moves from 8 toward the top of the range if n grows and holds); integrity battery landing; skill ladder; browser game.
We can beat: n=6, only gemini-4-carbon, v1.4 tier whose scripted gap narrowed; v1.5 not merged; ladder rungs showing +0.000 on easy; they have no multi-seat, no leak detector, no verifier rescore. We have no frontier row at all, so we trail on gap until lab lands one.
Ideas to copy (idea only): run the judge path via Harbor + OpenCode with the key name pitfall noted in our README; the oracle-vs-model same-world pair table; skill-ladder paired deltas with CI.

## Tick 5, 2026-11-14 15:15 Helsinki

Last-seen SHAs: justSilas e8a6fdf7 (= justSilas-gemini, now exists; was b4bcd4e), integrity2 cfeb59db, agents2 90e33542, env2 3965cbe3, fr8 8f2e01a1, v15 de9cc50e, v15-bias 9e4bda34. Unchanged: harness2 50d8a903, env2-ladder e2f74bb5, poisoned-inbox 9068b16a, all older branches. (git printed 7 and 8 char SHAs this time; compare by prefix.)

Merged into justSilas since tick 4 (their CEO log 14:38/15:40, env report 14:43, integrity report 15:40; all their claims, I did not re-run):
- Anti-cheat battery in `make reproduce` (bd446c6): 13 attack probes, stop-early ladder (solver cut at 25/50/75% and minus final accuse = exactly 0), control (= solver), replay of 299 v1.3 episodes all consistent (+15 s). `tests/test_anticheat.py` 21 tests.
- Harbor `ORACLE_POLICY=cheat` real run: -1.0 medium, -1.0 hard; fake reward.txt and rewriter ignored; /ledger and /admin 403 on all 12 token variants; no server files or CANARY_* env visible (`results/harbor/cheat/`).
- `CANARY_EPISODE_FILE` / token files: `make mcp`, frontier runner and hunter no longer put the seed or token in the server env (closes the bake-off `/proc` note).
- valid:false means infra only (two holes closed: agent text matching infra patterns; agent killing its server gets valid 0); a crashing policy or API error marks the episode valid:false, never a silent 0.
- **Momin's cheat corpus ported** (`canary/redteam/corpus.py`, `data/redteam/corpus.jsonl`, 129 rows): 774 injected runs, 0 accepted, 0 score changes. This is one of OUR assets landing (scorecard section A: cheat corpus now partial YES).
- Skill ladder merged (7e84d7d, v1.4, seeds 7000-7399, n=400): EV accusation rule costs -0.15 to -0.41, delay model -0.46 medium / -0.25 hard; careful mole, single canary, decoy, framing are within noise (flagged).
- `make hunt` on v1.4, 4 tracks x 4 modes: best non-solver 0.000, 0 violations (default budget). `make test` 592 passed / 6 skipped.

On branches only:
- v1.5 candidate (v15 de9cc50): solver medium 0.628 -> 0.641, hard 0.564 -> 0.571, acc >=97% hard; grok_tactics 0.371 hard; heuristic 0.002 hard; rumour_follower -0.995 hard. Scripted baselines ignore chatter, so the layer only bites LLM agents that trust rumours: Gate B Gemini spot check decides (CEO, 20:00). v15-bias: Gemini (gemini-4-carbon) chatter with sha256 cache and provenance, "adapted from momin" (our caching idea landing).
- RL mole (agents2): trained 80 it x 48 seeds, min regret ~0.26, solver acc 0.83; GRPO jobs 44424-44426 on V100s (FR8, WS3); WS4 v2 investigator eval ~22:00.
- Gemini exploit hunter dropped; Swarm on `gemini-track`. Harbor gemini-4-carbon demo (n=6, 0.50 vs oracle 0.76) unchanged.

Read: their integrity story is now closed on every point their own bake-off raised (Harbor boot, cheat run, env seed, valid filter). Expect integrity 24-25 and craft 13-14 on a re-score; gap still depends on Gate A n>=20 gemini-4-carbon.
We can beat: gap n=6 only (no n>=20 yet); v1.5 unproven; ladder shows 4 of 6 rungs flat; real frontier row still missing on our side.
Ideas to copy (idea only): their replay-consistency flag and stop-early ladder on our reference (lead-reward); valid:false = infra-only audit (lead-lab); `CANARY_EPISODE_FILE` style secret-out-of-env launch (lead-env).

## Correction to ticks 1-5, 15:23 Helsinki: our side moved

Earlier ticks described our weaknesses from bake-off 3 (07e17ee) and my 814a723 run. Corrected by lead-env and lead-lab, checked against momin where I could:
- finance_ap oracle: lead-env reports 1.000 on the needs-seat days incl. 1003/1008/1013/1018 on momin 357214a7 (procedure background, requester-table fix 9fa41d4, strategy-docs fix 90090a33), self-checks 15 PASS 0 WARN. Checked: `web/results/frontier/gaptable.md` on momin shows oracle 1.000 [0.84, 1.00] and fair reference 0.600 [0.39, 0.78] on days 1000-1019 x3, procedure background 9fa41d4. I did not re-run `make eval`.
- Harbor verifier: `environment_mode = "separate"` (`harbor/build.py` line 21), `results/harbor/separate-verifier-runs.txt` on momin: harbor lint exit 0, oracle reward 1, nop 0, exploit agent (rewrite reward.txt, /logs attacks) 0; opencode gemini-3.5-flash 180 s timeout, day unfinished, 0 (about $0.64). So the shared-verifier / chmod 777 /logs point is closed on the branch. A Harbor cheat-solution run is next (env-harbor).
- Real frontier rows exist (lead-lab, momin 5c3c8b0): Gemini 3.5 Flash 5 days x 3 = 1/15 (0.067, false accusation 0.73) and Gemini 4 Carbon 15 rows x 3 = 0/15 (as first measured; the prompt understated the call budget, so this is NOT a gap result; the true-budget Carbon headline row is due ~16:30), per-run cache tarballs under `results/frontier/gemini-3.5-flash/b06e6ad/` (checked present), each row verifier-rescored with 0 mismatches (lead-lab, not re-checked). They show `pending` in the headline gaptable until a bg_version tag fix lands. Carbon true-budget rerun and Flash 1000-1019 x3 in progress. I will not write "no real frontier row" any more.
- Secrets: lead-env says salt+token stay in the sidecar only, never in the agent container (their equivalent of Silas's seed-out-of-env).
Net: our real rows exist but are not yet a gap result (Carbon 0/15 had an understated call budget; Flash 1/15 b06e6ad prompt status asked of lead-lab, unlabelled until answered; scripted sleeper) against Silas's n=6 Harbor+OpenCode pair; neither reaches n>=20 yet. Scorecard section C is updated to match.
- lead-reward additions (momin 155ebfce, 357214a7): judge-runnable Harbor cheat agent covering every known Harbor cheat in one agent, plus isolation tests (X73 setsid/nohup/renamed/setuid attackers); stop-early ladder on our reference already exists (`make probes`, stop_ref at 25/50/75%) and replay consistency (rescore of every results/ run). So the earlier "ideas to copy" for stop-early ladder and replay consistency are already ours; the tick 2 and 4 lines saying we lack them are wrong. Canary port #2 (integrity probes) is `origin/sleeper/rw-exploit-canary-probes` @9439c03b off justSilas ded822e8: 143 pass, 1 xfail, nothing scores above the rules; findings: compose passes GEMINI_API_KEY to the sidecar without need, a latent uncounted crashing call at `mcp_server.py:149`, cap checked after the call. `control_pad` follows on the same branch.
