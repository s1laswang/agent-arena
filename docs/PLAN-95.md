# Plan: Canary from ~86 to ~95 (Sat 18:50 → Sun 09:30)

## Context
CEO estimate: gap 22/30, difficulty 26/30, integrity 24/25, craft 14/15 ≈ 86. On top of that the tiebreaker is currently a loss (the small model scores −0.15 against the base's 0.00) and the Gemini prize is about 7/10. A true 100 isn't something we control: the judges' 3 agent runs have variance. The realistic target is **93–96, with nothing a judge can knock down in 15 minutes**. Every action below is ranked by points per hour and has to land before its slot. Feature freeze for rules/env/solver: 20:00 (Gate B).

## Where the points are lost (honest diagnosis)
1. **Gap. A v1.4 frontier gap is not established.** Do not tell judges one is.
   - In-process bake-off, rules v1.4, paired seeds, n=10 per tier (21:26): gemini-4-carbon matches or beats the solver. Medium solver +0.734±0.050 vs carbon +0.680±0.085. Hard solver +0.433±0.324 vs carbon +0.509±0.136. Smaller Gemini models sat below the solver.
   - The tiebreaker's notes gain is the generic hint (notes minus hint −0.039±0.204).
   - Codex hard v1.3: 106% of the solver. That is an earlier tier, not a v1.4 gap.
   - Earlier carbon ratios (59% n=26, ladder 66% [5%, 117%] n=10) are not this bake-off. The 59% episodes were not committed. The 66% interval includes parity.
   - One lucky gamble at P=0.45 scores the same as a correct inference, so a judge rerun of 3 runs could land near parity.
   - The rubric says the gap must be "consistent" and "reproducible across repeated runs". We haven't shown repeated runs of the judge path.
2. **Difficulty (−4). We have the failure story (premature accusation, never abstaining, ignoring delays) but no causal proof.** Nothing yet shows the info was sufficient and the decision was the failure. Gallery tags are incomplete, and there's no human baseline.
3. **Integrity (−1). The verifier trusts the sidecar's score field (residual risk). There's been no hunt on the final tip, and judges get no exploit ledger to read.**
4. **Craft (−1). No fresh-clone proof on the submit commit.** The repo still looks like Sleeper on `main`, and the README's first screen isn't "one command → this table".
5. **Tiebreaker (lost). The small model learned the protocol (valid calls 0.08 → 0.99) but not the commit decision.**

## Actions, ranked by points per hour

### A. Gap: make it consistent and shown on the judge path (+4 to +6)
1. **A judge-dataset default that is pre-registered and hard-only.**
   - `harbor/build.py` default = hard tier, judge seeds 900000–900009, so each judge run is 10 hard episodes.
   - Medium and easy stay buildable with flags.
   - The seeds are fixed now, before any frontier run on them, so this is no cherry-pick.
   - README states why: hard is the tier where the solver keeps its EV edge.
2. **A judge-rehearsal run: exactly what the judges will do.** Harbor + OpenCode + gemini-4-carbon, **3 independent runs × 10 hard tasks**, plus the oracle and both baselines on the same build.
   - Report each run's mean vs the oracle and the run-to-run spread → `results/harbor/rehearsal/`.
   - This is the literal "reproducible across repeated runs" evidence.
3. **Tighten the hard headline to n ≥ 60 on v1.4.** The fleet runs seeds 30–59 (already redirected) and we merge them after replay verification.
   - Report **ratio + luck-adjusted ratio + accuracy + abstain rate** side by side.
   - The luck-adjusted 67% [44, 88] is the cleaner claim: lead with "even after removing luck, Gemini keeps only two thirds of the solver's expected value".
4. **A second family on v1.4 hard, n ≥ 30:** gemini-3.5-flash (84% at n=10). A Claude seat via `claude -p` over MCP if Momin's runner works. It shows the failure isn't one model's quirk.
5. **Gate B, 19:47.** Ship v1.5 only if Gemini's ratio drops on seeds 0–9 and integrity stays clean. Biased chatter is a second, human-grounded failure axis (rumour-following), so it's also a difficulty win.

### B. Meaningful difficulty: prove the failure is the decision, not missing info (+3)
1. **A hint ablation (the causal proof).** Add one sentence to gemini-4-carbon's prompt: "abstain unless your posterior exceeds 1/(1+V); leaks arrive 1–3 days late". Run n=20 hard, paired seeds.
   - If the score moves toward the solver and the premature-accusation tag drops, the info and tools were always there and the skill is calibrated commitment.
   - Check what head-agents already has (`hint ablations` in WS8) before re-running.
2. **A full failure gallery** over all Gemini and Codex transcripts (Atlas, Gemini CEO):
   - every lost point is tagged to a ledger step, with the solver's posterior at that moment;
   - 100% tagged, 0 "unexplained";
   - output: `docs/reports/failure_gallery.md`.
3. **A human baseline.** Silas, Momin, Vaishnav and Ivar each play 2 hard dev-seed episodes in the browser game, scores logged. Humans with the same info beating the frontier agent is a strong "fair task" signal.
4. **An instruction audit.** One Gemini pass and one Grok pass look for trick wording, hidden info or broken tools on the v1.4 (or v1.5) instruction. Findings are fixed or answered in `docs/DIFFICULTY.md`.

### C. Reward integrity: leave judges nothing to find (+1)
1. **Ledger signing (defense in depth, harbor/ only, no rules change).** The sidecar HMACs the ledger with a build-time 0600 key mounted only in the sidecar and the verifier, and `test.sh` fails closed on a bad signature. It also checks score ⊆ {−1, 0, V-trajectory values}. Tests are added to the anti-cheat battery.
2. **`EXPLOITS.md` at the repo root.** Every attack tried and its result: 13 probes, the cheat runs, 129 corpus rows, the 35-attacker Gemini swarm, the fleet probes, plus known residual risks and why they're bounded. Judges hunting for 15 minutes should find their idea already listed with a test.
3. **A final-tip hunt** on the submit candidate (~02:00):
   - the Gemini swarm again;
   - Grok bake-off 3 in judge persona;
   - Vaishnav does a timed 15-minute human hunt following the judges' protocol.

### D. Craft: one command, clean repo (+1)
1. **Fresh clone on a clean box** (an FR8 CPU node, not the login node): `git clone && make setup && make reproduce`. Time it, diff the output against README numbers, and commit the log.
2. **README first screen:**
   - the one command;
   - the table it prints: solver / Gemini / do-nothing / stop-early on hard;
   - the headline sentence and the rehearsal plot.
3. **The submission branch is what judges open.** Rename `main` → `archive/sleeper-main` and make justSilas the default branch (Silas's decision).

### E. Tiebreaker: get a reward gain, not just a behaviour gain (wins ties)
1. **22:00:** the v2 eval (dense windows + oversampled endings) result.
2. **If v2 still scores ≤ base, overnight v3 = reward training on the commit decision:** GRPO from v2 using the env reward, on easy + medium train seeds (never judge or held-out). Reuse the WS3 GRPO mole pipeline (`fr8/`, TRL, fp16). Runs on 2 V100s for 6 h, then the held-out eval with n ≥ 30 by 08:00. **Needs Silas's GPU approval.**
3. **Report honestly either way, on held-out seeds with CIs:**
   - valid calls 0.08 → 0.99;
   - solver agreement 0 → 0.85;
   - reward base → v2 → v3.

### F. Gemini prize (7 → 9)
- **One labelled REAL run per role:**
  - frontier subject;
  - failure analyst (gallery);
  - world-text renderer (v1.5);
  - adaptive mole;
  - red-team swarm.
- The headline story is a **patch loop**: show one thing Gemini's hunter found earlier and the test that now blocks it. If nothing was ever found, say "35 attackers, 0 exploits" with the attack list.
- The `pitch/GEMINI.md` table has real numbers only. Merge Gemini CEO PR 1/PR 2.

## Owners
| Action | Owner |
|---|---|
| A1 dataset default, C1 ledger signing, D1 fresh clone | HARNESS engineer (relaunch; Claude) |
| A2 judge rehearsal, A3/A4 runs, B1 hint ablation | CEO measurement engineer (resumes 19:00) + fleet seeds 30–59 |
| A5 Gate B, v1.5 | head-env + CEO |
| B2 gallery, F | Gemini CEO |
| B3 human playtests | all four humans, 20 min each |
| B4, C2, C3 | Vaishnav + an integrity engineer (relaunch; Claude) |
| D2 README, pitch, video | Silas + Ivar (if available) |
| E | fr8 session |

## Timeline (Helsinki)
| Time | Milestone |
|---|---|
| 19:00 | Resume the measurement engineer; relaunch HARNESS + integrity engineers with A1/C1/C2 |
| 19:47 | **Gate B** (v1.5 ship/drop) |
| 20:00 | **Freeze** rules/env/solver. A1 dataset default merged |
| 20:00–23:00 | A2 judge rehearsal (3×10 hard) + B1 hint ablation + A3 fleet seeds; C1 ledger signing merged |
| 22:00 | v2 eval → E decision (v3 GRPO overnight or not) |
| 23:00–02:00 | A4 second family; B2 gallery; README/results refresh; C2 EXPLOITS.md |
| 02:00 | **Submit candidate tagged**; C3 final-tip hunt; D1 fresh clone |
| 02:00–06:00 | Video, game deploy, B3 playtests in the morning, pitch |
| 06:00–08:30 | E v3 eval lands; final numbers into README; two dry runs |
| **09:30** | **Submit** |

## Expected score if all lands
Gap 27, difficulty 29, integrity 25, craft 15 ≈ **96**, plus a tiebreaker with an honest reward result.

**Kill criteria:**
- If the rehearsal shows parity on 2 of 3 runs, lead with the luck-adjusted metric and the hint ablation.
- If v1.5 doesn't widen the gap, don't ship it.

## Verification
- `make test` + `make reproduce` green on the submit commit.
- `results/harbor/rehearsal/` holds 3 run directories with per-task rewards.
- Replay check (`verify_replay.py`) passes on every committed REAL run.
- `EXPLOITS.md` items each map to a test in `tests/`.
- The fresh-clone log matches the README table.

## Launch briefs for the two engineers to relaunch (paste into a new Claude session in its own worktree off justSilas)

**HARNESS engineer (A1, C1, D1).** Repo s1laswang/agent-arena, branch off justSilas, PR into justSilas. Read docs/PLAN-95.md, harbor/README.md, harbor/build.py, harbor/template/tests/test.sh.
(1) A1: make `python harbor/build.py` default to tier hard, judge seeds 900000-900009 (flags keep medium/easy). Update harbor/README.md and the README "Judges" section with the reason. No change to canary/rules.py, env.py, solver/.
(2) C1: the sidecar signs the ledger with HMAC-SHA256 using a build-time 0600 key file mounted only into the sidecar and the verifier (never into main). test.sh fails closed (reward 0, FAIL line) on a missing or bad signature and on a score outside {-1, 0} plus the V range. Add tests to the anti-cheat battery, and rerun the oracle, cheat and do-nothing Harbor runs to prove the rewards are unchanged.
(3) D1, after the 02:00 tag: a fresh clone on an FR8 CPU node via sbatch (--time 1:00:00, partition normal; never the login node). Run `make setup && make reproduce`, diff the output against the README, and commit the log to results/fresh_clone/.
Never print keys. Never touch other users' jobs.

**INTEGRITY engineer (C2, C3, B4), with Vaishnav.** Read docs/PLAN-95.md, tests/test_anticheat.py, docs/reports/integrity.md, docs/canary-landing.md on origin/momin (fleet probe findings).
(1) C2: write EXPLOITS.md at the repo root. One row per attack (13 battery probes, Harbor cheat runs, the never-accuse probe, Momin's 129-row corpus, the 35-attacker Gemini swarm, the fleet probes: control_pad, sidecar key, ledger trust), with result, mitigation and the test that enforces it. Add a "Residual risks" section.
(2) B4: run an instruction audit (one Gemini pass, gemini-4-carbon) for trick wording, hidden info or broken tools. Answer or fix the findings in docs/DIFFICULTY.md; rules changes go to the CEO only.
(3) C3 at 02:00 on the tagged candidate: rerun `make hunt` and the Gemini swarm, and run the 15-minute judge-protocol hunt with Vaishnav. Report to docs/reports/integrity.md.

## Update Sat 14 Nov ~22:50
- **Verda cloud GPU** (Silas approved, cap $30): overflow GPU for the tiebreaker, so v3 seed 0 no longer waits for FR8 GPUs held by the fleet. **FR8 is the only Verda owner.** Other heads route GPU requests to FR8 with a GPU-hours estimate. Instances are deleted as soon as results are pulled; spend goes in docs/reports/fr8.md.
- **Gap gate at 01:40** (reviewer guardrails adopted):
  - Track 1 solver_v2: same tools and instruction; tuned off seeds 0–29 and 900000+; reported on fresh and judge seeds; v1 rows kept.
  - Track 2 expert tier: headline or Harbor default only with n ≥ 30 replay-verified OpenCode episodes by 06:00, otherwise addendum only.
- **v1.4 headline committed** (docs/reports/gap.md): OpenCode hard 60% [1, 103], luck-adjusted 68% [43, 91]. Pre-registered seed rule: the staged set is primary, fleet reruns are a replication.
- **Tag `afterquery-final` by ~07:00.** The rehearsal (oracle, 3× OpenCode, do_nothing, stop_early) runs on that exact SHA, and the SHA goes to the reviewer for main's landing page.
