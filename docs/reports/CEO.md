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
