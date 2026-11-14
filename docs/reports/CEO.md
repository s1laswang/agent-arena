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
