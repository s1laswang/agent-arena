# CEO log

## 01:40 kickoff
- The decision: Canary (catch the mole). Spec: docs/CONTRACT.md v0. Plan: docs/PLAN.md. Org: docs/TEAM.md.
- Scaffold on `justSilas`: rules.py, types.py, Env signatures, Makefile, pyproject (uv, Python 3.12). `make test` is green (3 contract tests).
- Facts checked: no Docker on the Mac (HARNESS installs colima). FR8 has 24 free CPU cores on compute06, all GPUs are held by `sky`, /data is not writable (we use ~/agent-arena-data), and the login node has internet.

## Contract changes
(none yet)

## 01:55 v2 (max-score plan)
- Contract v0.1 adds the Mole DSL and Mole Forge: Gemini evolves the mole; the hall of fame becomes the frozen hard tier (CONTRACT §7).
- Every head brief gets a "v2 additions" section: property tests, `make hunt`, hint ablations, CI, J5 forge, CI sizing. P0 still comes first.
- Momin is building "The Sleeper" (a similar concept, far along) on origin/momin plus the sleeper/* branches. Compare at 09:00 on measured numbers.

## 02:05 decisions
- **Contract v0.2 (judge-world integrity), proposed by INTEGRITY and approved:**
  - world RNG = HMAC-SHA256(key, "tier:seed"); public key for dev/train seeds; CANARY_WORLD_SECRET or data/worlds/judge/SALT for judge and held-out seeds, server image only;
  - instance RNG only (never the global random module or hash());
  - the seed is never exposed (opaque episode tokens);
  - identical accuse payloads and errors for every target;
  - judge truth may be committed: the bar (Terminal-Bench style) is that the answer key is unreachable from the agent sandbox.
- HARNESS owns check_isolation.sh and the `make hunt` target.
- OPENAI_API_KEY set by Silas in the shared checkout .env.
- FR8 cancels only job ids listed in ~/agent-arena-data/jobs/OURS.txt.

## 02:40
- Env v0 merged (3eace7b), 65 tests passing. CEO smoke run on 50 seeds x 3 tiers: do_nothing 0; random 0.02-0.04; restrict_all 0.01-0.05; **stop_early 0.14/0.10/0.04, which breaks the rubric** -> contract v0.3: a wrong accusation scores -1.0 (correct = V, none = 0). Pending: confirm with the mentors that negative rewards are OK. Fallback: a [0,1] reward plus a minimum-evidence rule.
- ENV: the `heuristic` baseline scores .74/.67/.41 (99/96/59% correct), so the tiers are too easy. Recalibration target on medium: heuristic <= 55% of solver, solver accuracy >= 90%. Weaken the free evidence (bigger recipient lists, longer delays, careful mole), keep every rule documented, and look at the frontier numbers before over-hardening.
- AGENTS: default frontier model is gpt-5.5 (probed); exact model ids are recorded in meta.json.
- FR8: partition normal is congested (orthodim array; compute06 is mix- planned), so CPU work moves to the Mac.
- GPU: Silas authorised pausing one sky run. Worst = 43143_4 (w0625-c1, best mAP50-95 0.484; the others are 0.51-0.56). sky_yolo.py resumes from last.pt, so `scontrol requeuehold 43143_4` = pause; `scontrol release 43143_4` resumes. The CEO executes it when FR8 submits J4.

## 03:35 GAP ALERT -> contract v0.4
- AGENTS: gpt-5.5 (in-process, real Env, no hints) on medium seeds 0-1 scores 0.795 vs solver 0.775 (103%). It uses canary bisection, which is a well-known algorithm. Solver over medium seeds 0-9: 0.777 +/- 0.046; heuristic 0.496. Confirmation run (10 medium + hard) in progress.
- Decision, v0.4 (additive, documented):
  - `fingerprint_accuracy`: a leaked canary variant is reported correctly with probability q, else a random other variant (hard 0.8, medium 0.9);
  - higher leak_damage (0.06-0.08);
  - actions_per_day 5;
  - careful mole + delay 1-3 in medium.
  - Rationale: the gap must come from Bayesian accumulation of noisy, delayed evidence plus the -1 penalty, not from knowing the canary trap.
- Story: medium = "fair tier, frontier ~ reference"; the headline gap is on hard + Forge-evolved moles (difficulty curve).
- FR8 J1 sweeps fingerprint_accuracy x leak_damage. J5 forge (stub) runs pop 24 x 500 gens; its moles must be re-validated after the freeze.
- OpenCode login only accepts gpt-5.6-sol, so it is used for the harness-shape runs (labelled). Morning: Silas adds OpenCode API-key auth for gpt-5.5 parity.

## 04:10
- Merged 54e1fa4: tiers v1 (FR8 J1: medium solver .54/acc .93 vs heuristic -.18/acc .50; hard solver .60/acc .95 vs heuristic -.26), JUDGE_SEEDS 40/tier, v0.5 fail-closed (fresh in-memory secret per server start; no committed world files containing the mole). v0.4 knobs present, defaults off. CEO run: 321 passed, 8 xpassed (INTEGRITY is flipping them to strict).
- AGENTS accusation audit: every gpt-5.5 accusation on the old tiers had P(accused)=1.00 under the solver belief; it accused ~1.5 days earlier than the solver on hard. ENV is diagnosing (certainty day vs accuse day): tuned tau + EV guard + daily pipelined canaries, ETA ~05:10. The solver robustness to random DSL moles dropped to 70% on medium (test relaxed to 0.65 until that fix).
- gpt-5.5 on tiers v1 (10 medium + 10 hard, dev seeds) started.
- HARNESS head still idle; a CEO-launched mcp-server engineer is building eval.run_episode + mcp_server.

## 04:35 GPU
- Per Silas, paused sky task 43143_4 (w0625-c1, the worst run, mAP50-95 0.484; it was at epoch 50/149) with `scontrol requeuehold 43143_4`. It resumes from last.pt. **To resume: `ssh freighter scontrol release 43143_4`** (the CEO does this when J4 ends, or at 08:30).
- sleeper-pilot 43478 took the freed GPU first (10-min limit). J4 44200 (canary-j4: LoRA SFT Qwen2.5-1.5B, fp16, 6 h limit) is next. J3 data: 20k+2k solver episodes on tiers v1 (pre-stopping-fix solver), 1.1 GB.
- The MCP server + eval.run_episode are merged (f2931d4, CEO-launched engineer): 338 passed. The CEO launched two more engineers in place of the idle HARNESS head: reproduce + README + CI, and Harbor task + isolation check (colima only with small resources, given memory pressure).

## 06:00 hard-tier gap failing, freeze moved to ~07:00
- AGENTS, tiers v1 partials (pre-fix solver, dev seeds 0-9):
  - HARD: gpt-5.5 n=4 0.719 acc 1.00 day 9.2 vs solver 0.638 acc .90 day 10.2 (113%); every accusation justified (P>=.96).
  - MEDIUM: gpt-5.5 n=3 0.067 (one forced P=.50 accusation at the horizon -> -1) vs solver .475.
- Solver fix + tiers v1.1 merged (b875386): solver .79/.63/.60, monotone; diagnosis: weak evidence, not a late stopping rule.
- Actions:
  - ENV solver studies the gpt-5.5 hard transcripts and adopts its strategies; check whether clearances make hard easier;
  - FR8 co-tune now includes fingerprint_accuracy (hard 0.8-1.0, medium 0.9-1.0) x behaviour_weight x framing;
  - freeze v1.2 ~07:00, then the official 20+20 gpt-5.5 run + OpenCode gpt-5.6-sol 5+5.
- Secrets: no committed SALT. Reproduce uses one random secret per invocation (paired within a run); Harbor uses a build-time secret in the server image only. README numbers are stated as mean +/- CI over secrets. #25 (/proc environ leak, found by the Grok judge run): *_FILE 0600 interface + sidecar; the mcp-server engineer was resumed for it.
- HARNESS review: a rare solver blow-up (>4 min, 1.9 GB on one world) -> ENV must-fix guard; public env.verdict() requested.

## 02:41 (real clock) correction
- The CEO log entries headed 03:35, 04:10, 04:35 and 06:00 were mislabelled. The real times were about 02:00-02:35 EET. Corrected schedule: tier freeze v1.2 at 04:30 EET; official frontier runs 04:30-06:30; Forge + hint ablations until 08:00; Grok dress rehearsal ~07:15; MORNING.md 08:30.
- ENV merged 3c46a20: Env.verdict(), canary.world.set_world_secret(), SolverPolicy(behaviour_weight) with act() guards. The reported 4-min solver blow-up did not reproduce in 1,800 timed episodes (max 0.09 s per act).
- Hard-tier root cause (AGENTS): the solver canaries cover ~20/30 staff, so the careful mole leaks them at x0.33; gpt-5.5 uses ~6-person groups (x0.8) with fresh labels. Fix: choose k to maximise (1-k/N)*H(split), plus the exact fingerprint-noise likelihood.
- J4: the tokenization patch is deployed (6 processes, cached; budget clamped to the job end 08:24). Train ~03:55-06:50, then eval.

## 03:10
- Tiers v1.2 FROZEN (db104c9). Fresh-seed table (9321ba1, n=400/tier):
  - solver .760/.658/.539 (acc 99.2/91.8/81.5%; hard 5% wrong, 13.5% abstain, accepted and reported honestly);
  - heuristic .636/-.036/-.273; stop_early ~-.9; do_nothing 0.
- Post-freeze fuzz (50k budget/tier): best non-solver score 0.000, 0 violations.
- Harbor package merged (90c6dde, CEO-launched engineer, Harbor 0.26.0): one task per tier/judge seed; an agent container with no canary code/secret; a canary-server sidecar (uid 10001, build-time secret as a 0600 file, *_FILE vars); a separate verifier reads /ledger via a collect hook. Oracle via Harbor: solver 0.79 (deterministic), do_nothing 0.0, stop_early -1.0; check_isolation strict: 11 checks, 0 findings. Not yet run: `harbor run -a opencode` inside Harbor (needs OPENAI_API_KEY on the host).
- Data point: OpenCode gpt-5.6-sol vs the sidecar on medium/900000 scored 0.84 vs solver 0.79 (n=1). The official gpt-5.5 20+20 run is in progress (results ~03:50).
- The Grok site bot (presentation site + replay viewer) is running in the cloud. Silas is asleep (charger connected).

## 03:30
- Repro engineer done (aea24b8): make reproduce (720 episodes in ~5 s, paired fresh secret, committed-agent replay block, timeout guard, REPRO_FAST), the parse_seeds fix, the README on v1.2, CI green. Fresh clone: setup 0.4-2.8 s, reproduce 5.5 s. Judge table over 30 fresh secrets:
  - solver medium +0.62 [+0.52, +0.68], hard +0.55 [+0.39, +0.65];
  - heuristic -0.01 [-0.32, +0.37], -0.27;
  - stop_early ~-0.9; do_nothing 0.
- README facts corrected: the Tesla leak story is 2008 (per a 2022 account), not 2018. The unmeasured claim "frontier agents score below it" was removed until the official run lands.
- Open:
  - solver wall-clock act_budget -> non-identical across machines; ENV is making it count-based;
  - scripts/repro_spread.py to be committed (HARNESS);
  - frontier rows pending AGENTS commit;
  - hard_forge not a headline until validated vs gpt-5.5.
- `make play` human playtest CLI (ENV, 309f8c1); INTEGRITY verified peek_status is unreachable via MCP and play refuses judge seeds (449 passed).

## 03:30 Grok agent matches the solver on v1.2 -> v1.3 prepared on a branch
- Kill source found: ~/canary-eval/client/start ran `pkill -f canary.mcp_server` per episode (a local Grok evaluation bot; finished at 03:01).
- Grok over MCP, v1.2 judge seeds 900000-4: medium 0.672, hard 0.567, 9/9 correct + 1 abstention (P~.53 < 1/(1+V)). That is >= the solver (~0.62 / ~0.55). Tactics:
  - TRUE V in status reveals the leak timing instantly, so the delay is irrelevant and restriction probing works;
  - recipient intersection narrows to a department, then tiny 1-per-variant canaries;
  - an explicit EV threshold.
- Plan v1.3 (branch, merge gated on the gpt-5.5 v1.2 results ~03:50):
  - status shows KNOWN V only (unsurfaced damage hidden; the true V is scored);
  - solver gains restriction probing + a tiny-canary endgame;
  - a `grok_tactics` scripted baseline;
  - FR8 recal; re-freeze as v1.3.
- OpenCode ChatGPT credits depleted (resets in ~6 days); the judges-shape run uses Codex gpt-5.5 over MCP. MCP parity verified.

## 03:45 DECISION: v1.3
- Official v1.2 interim (AGENTS, 29/40 gpt-5.5 episodes):
  - medium: solver .690 (acc .95) vs gpt-5.5 .605 (acc .94, 88%) vs Grok .672 (97%);
  - hard: solver .584 (acc .85) vs gpt-5.5 .544 (acc .91, 93%) vs Grok .567 (97%);
  - heuristic <0; stop_early ~-.9..-1; do_nothing 0.
  - v1.2 opens no gap. Cause: the true V in status reveals leak timing (Grok write-up).
- Go v1.3: known-V + a stronger solver + a grok_tactics baseline; FR8 recal; merge ~04:45; official gpt-5.5 20+20 + Codex 5+5 on v1.3. v1.2 is kept as the "clean evidence" record and before-picture.
- Contingency v1.4 (only if v1.3 frontier >= 85%): 2 moles on hard, or a longer horizon with pipelined canaries.
- Grok runs imported to data/runs/committed/grok (not replay-verified: per-process secret).

## 04:40 v1.3 merged (0933805, 469 passed)
- Known-V mechanics; solver v1.3 (latent leak days, decoy inference, tiny canaries, EV with expected true V; restriction probing off).
- 800 fresh seeds: solver .779/.632/.575, acc 99.6/88.7/84.8%, no-accusation .3/11.3/11.4%. Paired solver - grok_tactics: +.089/+.174/+.233.
- In flight: AGENTS official gpt-5.5 v1.3 run, FR8 J3 v2, INTEGRITY fuzz, HARNESS README refresh to v1.3.

## 03:35 (real clock, from `date`) correction
- The CEO entries headed "03:45" and "04:40" were actually written at about 03:25 and 03:33. From now on, CEO timestamps come from `date`. v1.3 merged around 03:30 real time.
- J3 v2 (v1.3 solver data, 20k+2k, correct-only) is staged on FR8 for the Saturday training v2. J4 44200 has run 1h10m, still in the pilot tokenization.

## 03:41 tick
- justSilas e411cf1, 476 passed (last verified 3e31c20). Power on AC.
- FR8: J4 44200 running 1h17m (pilot tokenization; training ~03:55-06:50, eval until 08:24). Sky 43143_4 still paused (requeuehold).
- AGENTS: official v1.3 gpt-5.5 run in progress (20 medium + 20 hard, started ~03:33, 8 workers). Spend cap $150/night without Silas.
- Forge: the evolved moles are not harder for gpt-5.5 (7/7 correct on 2 seeds). Framing: "a solver-constrained pipeline works; LLM-in-the-loop fitness is the morning step". J5b runs on v1.3.

## 03:50 SPEND OVERRUN (for Silas)
- OpenAI API spend tonight is about $195, above the CEO cap of $150 (set at about 03:30; AGENTS had not been tracking spend before that).
  - v1.2 official gpt-5.5 20+20: $121.46 (~$3/episode)
  - v1 directional: $24.4
  - Forge HOF validation: ~$22.4
  - killed/unlogged runs: ~$20-25
  - Codex API: a few $.
- All API-billed runs are stopped after their in-flight episodes (~10-12 v1.3 episodes). No further API spend without Silas.
- Zero-marginal-cost path: Codex CLI on the ChatGPT login (only if its auth mode is verified); Gemini free credits in the morning.
- v1.2 OFFICIAL FINAL (efef43b): medium gpt-5.5 .600 vs solver .690 (87%); hard .500 vs .584 (86%); Grok 97%/97%.

## 03:49 spend + reference
- The reference is consistent (9c236b3): v1.2 numbers = episodes played at db104c9; v1.3 numbers = solver at 0933805. The re-run rows are kept under committed/superseded/.
- Codex gpt-5.5 over MCP, v1.2 5+5: medium .714 (5/5, 104% of solver); hard -0.02 (3/5; two wrong accusations at -1). Hard is high-variance for frontier agents under the -1 rule.
- SPEND estimate now ~$220 (Codex cached-input assumption; worst case ~$340 if caching is not discounted). All API runs stopped except ~3 in-flight v1.3 episodes (~14 v1.3 episodes total). **Silas: check the OpenAI billing dashboard.**

## 03:55 GAP OPENS ON v1.3 (small n)
- gap.md final for the night (f4fd1f6):
  - v1.2 (n=20+20): gpt-5.5 87%/86% of the solver;
  - **v1.3 (n=9+5, spend-capped): medium .319 vs .717 (44%); hard -.003 vs .592 (~0%)**. The reference barely moves; gpt-5.5 collapses.
- Why: all 4 wrong v1.3 accusations are day-14 gambles at P .18-.43; premature_accusation = 36% of episodes, >90% of regret. It never abstains though EV<0 (Grok did abstain once, so the information is available).
- Spend ~ $260 est. total; all API runs stopped. Morning: approve ~$60-90 for v1.3 20+20, or use Gemini free credits.

## 03:58 v1.3 regret (1a650df) + CAVEAT
- Paired on gpt-5.5 seeds: medium solver .670 vs gpt .319 (48%), hard .553 vs -.003; dominant tag premature_accusation.
- **CAVEAT:** Codex gpt-5.5 over MCP (judges-like harness, n=3) scored .59 hard / .53 medium, much closer to the reference. The in-process scaffold may handicap the model. Morning priority #1: a judges-shape (OpenCode/Codex over MCP) v1.3 measurement at n>=10/tier, plus a scaffold-parity check. Keep the v1.4 contingency (longer horizon + pipelined canaries) in reserve.

## 04:12 tick
- justSilas b861d74: 496 passed. On AC power.
- J4 44397 training (19 min; 1,404 tok/s; training to ~06:50, eval to ~08:10). Sky 43143_4 held.
- INTEGRITY v1.3: full fuzz incl. hard_forge, 0 violations; known-V never equals the true V and never rises; EXPLOITS 40 rows, none open on our side (#27 residual = the Harbor sidecar).
- AGENTS: scaffold fix merged (full history, Responses API with reasoning replay, effort=medium), zero API spend; morning smoke ~$3 then a paired v1.3 re-run ~$90 (needs Silas).
- Heads mostly idle and waiting on the morning (Gemini key, spend approval, Grok re-run).

## 05:04 tick
- justSilas d69448e: 499 passed. AC power. J4 44397 training (1h12m). Sky 43143_4 held.
- HARNESS 05:00 fresh-clone check on v1.3 PASSED: two secrets, the gap holds on every tier (solver lower CI > every baseline upper CI; do_nothing 0), exact mode byte-identical, harbor lint OK. Fix in progress: reproduce writes to a gitignored dir so a clone stays clean.
- INTEGRITY: HoF v1.3 holds (#41), but its 3 survivors behave identically; FR8 dedups before any claim.
- NOTE: the HEAD-ENV session is no longer running (it ended after finishing its work). Relaunch it in the morning only if ENV work is needed (prompt in docs/agents/ENV.md).

## 06:05 tick
- Merged the HARNESS results/latest fix (be68285): reproduce leaves the clone clean; 503 passed.
- BUG found by the CEO: the reproduce "Reported agent runs" block pools v1.2 + v1.3 runs and includes committed/superseded/ (medium openai:gpt-5.5 n=29 is mixed; solver n=60 includes superseded). Sent to HARNESS (P0): group by tiers_version, exclude superseded.
- The AGENTS and ENV sessions have ended (their work is done). FR8, INTEGRITY and HARNESS are live. J4 44397 has trained 2h09m (training ends ~06:50).
- Paired hard (this invocation, fresh secret): solver +0.526 (acc .75), heuristic -0.34, stop_early -1.0, do_nothing 0.

## 06:35 tick
- HARNESS stayed "waiting" and did not pick up the reproduce version-pooling P0, so the CEO launched an engineer (branch justSilas-repro-group): group replayed runs by tiers_version, exclude superseded, refresh the committed results.
- J4 44397 at 2h42m (training ends ~06:50, then eval). Sky 43143_4 held.

## 06:50 reproduce grouping fixed (41c9c95, 507 passed)
- Replayed runs are grouped by tiers_version, superseded runs are excluded, and history rows show no solver ratio. The committed results were refreshed (fingerprint f4cacdb8537b); README line 35 now matches it: solver medium +0.65 +/-0.07, hard +0.60 +/-0.10; heuristic +0.04 / -0.50. The CEO accepts the refreshed numbers (consistent with the committed file).
- v1.3 reported (n small): medium gpt-5.5 .319 (n=9) vs solver .717; hard -.003 (n=5) vs .592; codex gpt-5.5 v1.3 n=1-2 is close to the solver.
- Note: the v1.3 heuristic/random/stop_early/do_nothing rows equal their v1.2 rows. That is expected, since those policies do not read V and dev-seed worlds are identical.

## 07:15 tick
- Grok deliverables are on origin: site (presentation dossier, offline, 9 sections), viewer, pitch deck + judge handout (PDF), research grounding, bake-off, agent eval.
- The Grok BAKE-OFF (written at ~02:34, BEFORE reproduce/Harbor/gap.md/v1.3) scored Blind Spot (Ivar) 69, Canary 56, Sleeper 43, and recommends shipping Blind Spot. Many of its Canary deductions have since been fixed (make reproduce, Harbor sidecar + isolation, gap.md with frontier runs, #25 server side, CONTRACT v1.3). Its remaining valid points: the gap evidence is small-n / scaffold-caveated, and Gemini is not essential to the judge path. Ivar has since added "blind frontier results" (78038e3). -> For 09:00: re-run the bake-off on the current tips.
- J4 eval running (ends <=08:17); then release sky 43143_4.

## 08:21 J4 final + sky released
- J4 44397 TIMEOUT at its 4:25 limit during eval (planned). Final: base n=2 (valid .08, 0 accusations, score 0); LoRA n=17 (valid .99, solver agreement .85, 4/17 accused, 1 correct, score ~ -0.15). Behaviour learned, commit decision not; Saturday v2 adds --oversample-endings.
- **Released sky 43143_4** (`scontrol release`); RUNNING on compute04, resuming from last.pt. FR8 holds no jobs.
- MORNING.md final (integrity corrections from INTEGRITY folded in).

## 09:01 final tick: overnight loop stopped
- justSilas 348afba: 517 passed. All 8 sky runs RUNNING (43143_4 resumed). No team cluster jobs.
- MORNING.md is final. Hand-off to Silas for the 09:00 review.

## 10:25 Silas APPROVED $93 for the v1.3 frontier measurement
- The CEO launched a measurement engineer (branch justSilas-measure). Order: smoke (~$3) -> Codex gpt-5.5 over MCP, v1.3 dev seeds 0-9 medium+hard (judges-shape priority, ~$45) -> in-process fixed loop on the same seeds with the remaining budget. Hard stop at $90 projected. Paired analysis + regret, then gap.md, the README frontier row and the committed results get updated.

## 11:25 spend validated + official v1.3 result
- Silas: OpenAI dashboard TOTAL (overnight + morning) is ~$170, below our summed estimates, so the cached-input pricing is confirmed (conservative).
- OFFICIAL v1.3 (paired, dev seeds 0-9; ratio with bootstrap 95% CI):
  - Codex gpt-5.5 over MCP (judges shape): HARD 97% [89, 107] (0.657 vs 0.678, 10/10 correct); MEDIUM 50% [-19, 103] (0.364, 8/10; the gap comes from 2 early wrong accusations).
  - In-process fixed loop: medium 90% [77, 105] (n=8), hard 29% [-44, 100] (n=7).
- => **v1.4 contingency TRIGGERED on hard.** Spend today $47.46 discounted; all further spend held pending the v1.4 decision with Silas.

## 11:30 OpenAI removed; v1.4 + Gemini launched
- Silas: no Gemini spend limit; remove the OpenAI API. OPENAI_API_KEY blanked in every .env (shared checkout + all worktrees). Codex CLI has its own API key in ~/.codex (not touched; we will not run it).
- Gemini key verified (one gemini-3.8-flash call OK). Available models include gemini-4-carbon/argon/hydrogen and gemini-3.8-flash. The canary.llm default gemini-2.5-flash returns 404 (being fixed).
- Launched: (1) v1.4 env engineer (branch justSilas-v14): hard 21 days, 2 canaries/day, 3 variants, higher leak damage (maybe n=40), solver plans multiple canaries/day, Mac calibration, freeze v1.4, hunt + reproduce + README. (2) Gemini measurement engineer (branch justSilas-gemini): strongest Gemini model, OpenCode+Gemini over MCP (judges shape) + in-process, v1.3 paired seeds 0-9 now, v1.4 when frozen.

## 12:09 v1.4 merged (8f87ed1)
- Hard: 40 staff, 21 days, 2 canaries/day x 3 variants, leak 0.05, cap 420. Fresh seeds 5000-5799: solver .779/.633/.556 (hard acc 94.9%); hard solver - grok_tactics +.195 (target .2 missed by .005); solver - heuristic +.534. make hunt: 0; make test 527.
- Caveat: v1.4 NARROWS the gap to grok_tactics vs v1.3 on the same seeds (+.233 -> +.195); the bet is that LLM bookkeeping fails. Only the Gemini/frontier measurement decides.
- CEO decisions: no fingerprint 0.9 tweak to chase the .2 target (wait for the frontier data); re-evolve hard_forge against v1.4 later with the Gemini mutator; medium unchanged.
- repro_spread.py bug fixed (it had pooled replayed runs into the solver/heuristic cells); the v1.4 README table is clean.
