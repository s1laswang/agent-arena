# INTEGRITY report (HEAD-INTEGRITY)

## 02:00 status
- Done (verified: files committed): worktree `wt/justSilas-integrity`; hole checklist in docs/EXPLOITS.md; `tests/integrity_helpers.make_env` (skips while Env is a stub).
- In progress: spawning engineers baseline-fuzzer, exploit-hunter, props-probe (ETA first drop 03:30).
- Blockers: Env/MCP are stubs on justSilas; integrity tests are written against CONTRACT and will auto-activate. Need `env.world.mole` (or equivalent) exposed server-side for tests: asking ENV.
- Next 45 min: engineers build baselines + fuzzer + property tests against the contract.

## 02:15 status
- Done (verified: `make test` 32 passed / 20 skipped on justSilas-integrity after merging origin/justSilas): baselines (8 policies, `canary/baselines.py`), `canary/redteam/fuzz.py` (random/malformed/evolve/parallel_accuse/all, `--report`, `hunt()`), `fr8/j2_fuzz.sbatch` (not submitted), fuzzer unit tests incl. a planted-bug FakeEnv that the fuzzer catches.
- Verified on Env v0 (02:20): `make test` 92 passed / 1 skipped; `fuzz --mode all --tier easy --seeds 0-19 --budget 2000` → best non-solver score 0.000, 0 invariant violations, runtime ~1 s (`make hunt` fits easily).
- In progress: exploit-hunter (codex over MCP), props-probe (hypothesis + text probe + seed-not-exposed test).
- Asks to ENV: `env._world.mole`; ledger "accused" detail {"employee": id}; "day" in status/advance_day and "V" in status; accuse under a lock (check-and-set); non-dict args → ok=False, never raise.
- Next 45 min: run fuzz + baselines on Env v0 the moment it lands; first EXPLOITS rows with results.

## 02:40 status
- Done (verified: `make test` 163 passed / 2 skipped after merging origin/justSilas): props-probe merged (hypothesis property tests, explicit integrity tests, text_probe, monotonicity). Judge salt verified: judge worlds built without CANARY_WORLD_SECRET ≠ served moles (test_judge_salt). Added test_salt_never_tracked + `.gitignore` entry for data/worlds/judge/SALT.
- EXPLOITS.md unified to 9 rows; row 1 = stop-early v0 = 0.10 on medium → fix contract v0.3 (wrong accusation = −1.0), test updates in progress.
- In progress: props-probe → v0.3 sign properties; fuzzer → medium/hard fuzz + calibration + FR8 J2; exploit-hunter → codex over MCP.
- Next 45 min: v0.3 tests green on merge; text probe on medium 0-49; first codex hunt once MCP lands.

## 02:55 status
- Done (verified: `make test` 189 passed / 2 skipped / 8 xfailed): fuzz `--mode all`, seeds 0-49, budget 20000 on easy/medium/hard → best non-solver score 0.000, 0 invariant violations everywhere (all ~5 s). Baselines calibrated on 30 seeds/tier. v0.3 sign invariants in the fuzzer (xfail until v0.3 lands).
- **FINDING #10 (open, ENV):** access logs alone name the mole: LogsMinusDecoy (no canaries) is correct 71% easy / 33% medium / 19% hard at wait=9 (chance 8/5/3%) and beats the canary heuristic on easy+medium. Hurts "meaningful difficulty" (canaries optional). Proposed fix sent to ENV.
- FR8 J2 sbatch ready (untested on FR8), handed to FR8 head.
- Next 45 min: v0.3 + props round 2 merged; text probe; MCP exploit hunt once MCP lands.

## 03:10 status
- Done (verified: `make test` 230 passed / 4 skipped / 11 xfailed on justSilas f0ad3b2): props round 2 merged (score properties valid under v0 and v0.3), `logs_only` baseline + `test_logs_only_bound` (CEO bound easy ≤40%, medium/hard ≤2× chance; xfail until ENV recalibrates).
- Text probe, medium: stub 200 seeds 14/200 = 0.07 vs fair bar 0.074 (p=0.62); gpt-4o-mini 0/50 → no text leak.
- EXPLOITS rows 0–14: 12 hold, #10 open (ENV), #1 fixed by v0.3 (pending merge).
- Monotonicity: random 0.009 < most_logs 0.017 < heuristic 0.036 (medium, 50 seeds; CIs overlap). Solver/hinted LLM missing → plot incomplete.
- Blocked: MCP server not on justSilas yet → MCP hunt + Codex hunter waiting (HARNESS).
- Next: re-run full fuzz + bounds after ENV v0.3 + recalibration; MCP hunt the moment HARNESS lands.

## 03:30 status
- Done (verified: make test 260 passed / 6 xfailed / 2 xpassed on justSilas 7146062 + v0.3): v0.3 confirmed, stop_early mean −0.80/−0.96/−0.96 → EXPLOITS #1 fixed. Full fuzz (all modes, 3 tiers, 50 seeds, 20k): 0 violations, best non-solver 0.000 vs solver 0.80/0.76/0.74. 400k evolve on hard: 0 violations (#15).
- #10 partially: log-alone vs canary heuristic now OK on medium/hard; logs_only CEO bound still xfail on all tiers pending ENV recalibration.
- In progress: exploit-hunter (codex plumbing; MCP from CEO's mcp engineer ETA 04:00); monotonicity re-plot with solver.
- Next: MCP hunt the moment it lands; re-run bounds after recalibration.

## 03:50 status
- Done (verified: make test 305 passed / 8 skipped / 7 xfailed / 2 xpassed): exploit-hunter merged (codex hunter, stdlib MCP client, envshim server, MCP tests incl. 16-thread parallel accuse + ledger token, passing on envshim; real-server variants skip until canary/mcp_server lands). Props round 3: monotonicity medium random −0.66 < most_logs −0.49 < heuristic +0.64 < solver +0.74 (100 seeds); hard solver +0.73 vs heuristic +0.02; results/monotonicity.png.
- **CRITICAL #24 (open, ENV+HARNESS):** judge seeds fail OPEN: with no CANARY_WORLD_SECRET and no SALT file (= a fresh clone, i.e. what judges run), `_key()` warns and uses the public key; mole recoverable from public code (verified: seed 900003 → e03 both served and recovered). Found by codex white-box. Fix: fail closed + ship frozen judge worlds.
- #23 (open, HARNESS): dev/train seeds are public by design → MCP server must only serve keyed seeds to agents.
- Codex hunts: black-box (3 runs, envshim) 0 score, 0 flags; OpenAI moderation truncates many codex runs.
- Next: get #24 fixed and verified; real MCP hunt once mcp_server lands.

## 04:30 status
- Done (verified on justSilas 54e1fa4 + f2931d4): #10 FIXED (logs_only 28/1/3% over 100 seeds, CEO bounds met) and #24 FIXED (v0.5 fail-closed): xfails removed → strict tests. Full fuzz on tiers v1: 0 violations, best non-solver 0.000 vs solver 0.80/0.44/0.51.
- Note for CEO/ENV: on tiers v1 the solver scores lower on medium (0.44) than hard (0.51).
- Flaky test found: test_stub_hunt_fake_server_plumbing (~1/6 full runs); hunter engineer fixing (port 0 + health poll). Merges gated with pipefail.
- Real MCP server landed: hunter engineer running [real] MCP tests + codex black/white-box vs real server.

## 05:00 status
- Done (verified: make test 352 passed / 3 skipped / 1 xfailed on justSilas): test_solver_tier_ordering strict (ENV b875386: .79 > .63 > .60); #24 verified fixed; FR8 J2 (4M evolve, hard, pre-v1): 0 violations, best non-solver 0.000.
- External Grok judge run reviewed: re-found #24 (fixed) and NEW #25 HIGH: server secrets readable via same-uid /proc/<pid>/environ / `ps eww` → 1.0. Regression test tests/test_integrity_secrets.py (xfail strict) + attacker-primitive sanity test (passes on macOS). Interface CEO-approved: CANARY_*_FILE 0600 files, no plain secrets in exec env, Harbor sidecar primary. Owners: mcp-server + harbor engineers.
- In progress: exploit-hunter → flake fix (port 0 + health poll, 20 green runs), [real] MCP tests, codex black/white-box vs real server.
- Next: verify #25 when mcp_server lands *_FILE; re-run the Grok judge prompt on the tip; FR8 J2 rerun on tiers v1.

## 04:45 status (post-freeze, tiers v1.2 @ db104c9)
- Done (verified: make test 386 passed / 3 skipped on db104c9 merge): fuzz all modes, 100 seeds, 50k budget, all tiers → 0 violations, best non-solver 0.000. Baselines × 100 seeds: do_nothing 0; every other baseline mean ≤ 0 (stop_early −0.86/−0.88/−0.92, logs_only −0.55/−0.98/−0.98, heuristic −0.35/−0.88/−1.00); solver +0.79/+0.63/+0.60.
- #25 fixed server-side (50022ab, test passes); Harbor sidecar remains boundary (HARNESS).
- Flake fixed at root (20/20). FR8 J2 on v1.1: 0 findings; final v1.2 run requested. parallel_accuse summary now reports race count (it was never a no-op).
- Canary-surfacing question closed: canaries do surface on medium (verified directly).
- Next: Grok judge re-run ~07:15 on final tip; Gemini hunter when key arrives.

## 03:22 status (heartbeat; clock per CEO correction)
- No ENV/MCP changes since last sweep (frozen tiers v1.2). justSilas green: 456 passed / 5 skipped.
- Done since 04:45 entry: FR8 J2 final on frozen v1.2 (4M evolve hard+medium): 0 findings. peek_status/verdict unreachable by agents + `make play` refuses judge seeds (tests/test_integrity_peek.py). mcp_server SIGTERMs investigated: not integrity (a local Grok eval bot's pkill); codex hunters now run in read-only sandbox. v1.3 known-V tests ready (skip until shipped).
- EXPLOITS.md: 38 rows; open: none on our side (#27 residual = Harbor sidecar, HARNESS).
- Next: re-run fuzz + property tests when ENV ships v1.3; Grok re-run ~07:15; Gemini hunter when key arrives.

## 03:45 status (tiers v1.3 known-V @ 0933805)
- Done (verified: make test green after merge): fuzz all modes on easy/medium/hard (100 seeds, 50k) + hard_forge (50 seeds, 20k): 0 violations, best non-solver 0.000. Known V: 665 hidden-leak states, status/advance_day never equal true V, never rise (tests added). Calibration policies < solver on all 4 tracks (grok_tactics closest: easy .71 vs .79). peek_status unchanged & covered.
- EXPLOITS rows 38–40 (correction: earlier 03:22 entry said 38 rows; it was 37).

## 03:49 status (heartbeat)
- No ENV/MCP/baselines code changes since the v1.3 sweep (new commits are results/logs: official gpt-5.5 v1.2 runs, regret reports). No re-run needed.
- justSilas green after merge (see merge commit). EXPLOITS: 40 rows, none open on our side; #27 residual = Harbor sidecar (HARNESS).
- Waiting on: Grok judge re-run ~07:15 (Silas), Gemini key for the Gemini hunter.

## 04:20 status (heartbeat)
- No ENV/MCP code changes. New: Forge J5b hall_of_fame_v1.3 (3 evolved moles). Integrity check per mole (hard, 40 seeds): solver +0.554, do_nothing 0, stop_early/logs_only/restrict_all ≈ −1, fuzz 0.000 / 0 violations → holds (EXPLOITS #40).
- Flag: the 3 "distinct" HoF moles produce identical leak traces (seeds 6000/6001) and identical solver means → likely behaviourally equivalent; "3 distinct survivors" claim needs a dedup check (sent to FR8/CEO).

## 04:50 status (heartbeat)
- No ENV/MCP code changes. FR8 deduped HoF by outcome: v1.2 and v1.3 = 1 evolved mole each (gap.md corrected). Re-checked the surviving moles on the merged tip (hard, 30 seeds + fuzz 20 seeds): holds (see EXPLOITS #40).
- justSilas green. Waiting on: Grok judge re-run ~07:15, Gemini key.

## 05:19 status (heartbeat)
- No ENV/MCP/baselines code changes since 04:50 (new: HARNESS fresh-clone check on v1.3 PASS, reports). No re-run needed. justSilas green.
- EXPLOITS: 40 rows, none open on our side. Waiting on: Grok judge re-run ~07:15, Gemini key.

## 05:49 status (heartbeat)
- No changes on justSilas since 05:19. Nothing to re-run; justSilas green. Waiting on Grok re-run ~07:15 and Gemini key.

## 06:19 status (heartbeat)
- No ENV/MCP/baselines code changes (new: reproduce output path → gitignored results/latest/, reports). Nothing to re-run; justSilas green. Waiting on Grok re-run ~07:15 and Gemini key.

## 06:49 status (heartbeat)
- No ENV/MCP/baselines code changes (new: reproduce groups runs by tier version, judge table refresh, README). Nothing to re-run; justSilas green. Grok re-run expected ~07:15.

## 07:30 status
- Judge rehearsal on a FRESH GitHub clone of justSilas (no .env, no keys): `make hunt` was MISSING (HARNESS never added it) -> added Makefile target `hunt` (all 4 tracks, ~51 s): 0.000 best non-solver, 0 violations everywhere. Fresh clone: `make hunt TIER=medium` clean; seed_attack on judge seed 900007 -> None (v0.5 fail-closed holds). make test 507 passed.
- Grok judge re-run not yet on origin (latest grok-judge commit 00:28).

## 07:49 status — overnight summary for the 09:00 review
- **Reward integrity verdict:** no exploit beats the solver on the frozen tiers (v1.3 + hard_forge). 41 attempts logged in docs/EXPLOITS.md; every closed exploit has a regression test (#32 = inconclusive hunt record).
- **Real exploits found and closed (all with tests):** #1 stop-early lottery (v0: +0.10 medium → v0.3 wrong = −1); #10 logs alone named the mole 71% easy (→ tiers v1 recalibration, CEO bound met); #24 judge seeds fail open → public-key regeneration, 1.0 on 90/90 judge seeds (found by codex white-box + Grok judge; → v0.5 fail-closed); #27 server secrets readable from same-uid /proc environ (Grok judge; → CANARY_*_FILE, Harbor sidecar is the boundary); #23 dev seeds public (→ server serves judge/held-out only).
- **Held:** fuzz (random/malformed/evolve/parallel-accuse) up to 4M evals on FR8, all tiers → best non-solver 0.000; error/length parity; ledger token; 16-thread accuse race over real MCP; calls after end; V monotone; known-V hiding (665 states); seed never exposed; text-only probe ≈ fair bar; peek_status/verdict unreachable; calibration policies < solver; evolved moles catchable.
- **Baselines (frozen v1.2, 100 seeds):** do_nothing 0; every other baseline mean ≤ 0; solver +0.79/+0.63/+0.60.
- **Judge tooling:** `make hunt` (no keys, ~51 s, all tracks) verified on a fresh GitHub clone; `make test` green (517 passed).
- **Open / for the morning:** Grok judge re-run on the final tip (not yet run); Gemini exploit hunter when GEMINI_API_KEY is in (canary.llm wiring for hunter.py); codex hunts are weak evidence (OpenAI moderation cut 8/9 runs).

## 08:19 status (heartbeat)
- No code changes since 07:49. Reviewed docs/reports/MORNING.md §4 against EXPLOITS: accurate; sent CEO 3 nits (#25/#27 = one exploit, #23 missing, Grok re-run + Gemini hunter still open). justSilas green.

## 14:50 status (HEAD-INTEGRITY relaunch, branch justSilas-integrity2)
- Done (verified: `make test` 571 passed / 6 skipped; `make reproduce` x2 with 40 judge seeds and fresh secrets → "All probes blocked: yes"): **anti-cheat battery in make reproduce** (Vaishnav's Poisoned Inbox design). It has 13 attack probes, the stop-early ladder (solver cut at 25/50/75% and minus its accuse = exactly 0 on every seed) and the control (= solver on every seed). Output goes to results/latest/exploits.{json,md}. Merged by the CEO (bd446c6).
- Done (verified: tests/test_anticheat.py, 21 tests): replay consistency (299/299 v1.3 committed episodes re-grade identically; v1.2 and judge-seed runs flagged not-replayable), detached tool results, PYTHONHASHSEED independence, and the Harbor verifier failing closed on a bad, NaN, out-of-range or symlinked ledger.
- Done: docs/EXPLOITS.md section "Anti-cheat battery (runs in make reproduce)"; README paragraph.
- In progress: Harbor `ORACLE_POLICY=cheat` (harbor/template/solution/cheat.py). First attempt hung on a recursive `/**` glob over /proc (fixed with a bounded os.walk). Partial log before the hang: every token-less or guessed-token GET /ledger and POST /admin/reset returned 403. The rerun is in flight.
- Dropped per the CEO lane update: Gemini exploit hunter (now Swarm on gemini-track).
- Next: commit the cheat log and stop colima; then items 2 (CANARY_EPISODE_FILE for non-Harbor launches) and 4 (the valid:false audit).

## 15:40 status
- Done (verified: real `harbor run`; logs in results/harbor/cheat/): ORACLE_POLICY=cheat → **−1.0 medium, −1.0 hard**. The fake reward.txt and the rewriter were ignored; /ledger and /admin returned 403 on all 12 token variants; no server files and no CANARY_* env vars were visible; only 1 accusation was accepted. Colima stopped afterwards.
- Done (verified: ps eww on `make mcp` + tests/test_integrity_launch_env.py): item 2. make mcp, the frontier runner and the hunter launch the server with CANARY_EPISODE_FILE/CANARY_LEDGER_TOKEN_FILE only.
- Done (verified: tests/test_integrity_valid_filter.py, all 8 committed invalid episodes re-classified): item 4. valid:false = infra only. Two holes closed: the agent's own text no longer matches infra patterns, and an agent that kills its server gets a valid 0.
- Done (verified: 774 injected runs, 0 accepted, 0 score changes): Momin's cheat corpus ported (canary/redteam/corpus.py, data/redteam/corpus.jsonl).
- Done (verified: `make hunt` on v1.4, 4 tracks × 4 modes): best non-solver score 0.000, 0 violations. Item 3 used the default hunt budget, not a long one.
- `make test`: 592 passed / 6 skipped.
- Next: a long-budget hunt (item 3) if wanted; fold the corpus into the reproduce battery (currently 55 s, so it is kept as a separate CLI).

## S3 integrity session (s3-integrity, from Sat 23:00)
The canonical exploit ledger is [docs/EXPLOITS.md](../EXPLOITS.md) ("Judges: start here" at the top). The anti-cheat battery is Vaishnav's design.

### Sat 14 Nov 23:00–00:10 EET: one ledger, re-run on the justSilas tip (309b65f, then rebased onto 0f379cd)

- **Ledger merged.** The previous judge-facing draft (an old subagent worktree, uncommitted) is folded into `docs/EXPLOITS.md`. It adds "Judges: start here" (J1–J14: attack class, result, mitigation, enforcing test), Residual risks, and a "where your idea is covered" index on top of the full history. New history rows: #43–#44 (Gemini swarm), #45–#47 (Momin's fleet probes, 18:40), #48 (isolation), #49 (this re-run). Rows #0 and #1 were updated for the `stop_early` / `guess_day1` split. The draft's numbers predate the current battery; every number now comes from a committed file, and the file is named.
- **`make hunt`:** best non-solver 0.000, 0 invariant violations in all 16 tier × mode cells; solver 0.798 / 0.611 / 0.472 / 0.541 (easy / medium / hard / hard_forge). Log: `results/anticheat/hunt.log`.
- **Momin's corpus, widened to easy:** 129 rows × seeds 0-2 × 3 tiers = 1,161 runs, 0 accepted, 0 changed (`results/anticheat/corpus_eval.txt`).
- **`make anticheat-verify`** (on 309b65f): 96 rows rerun on 40 seeds × 3 tiers under the public secret, 0 differences.
- **Judge-protocol hunt** (`scripts/judge_hunt.py`, new): 12 wire-level attacks on the real MCP server, **12 of 12 held** (`results/anticheat/judge_hunt.md`). Correct vs wrong accusation: the agent's view afterwards is identical.
- **Gemini swarm w2b-008** (CEO request): flagged "confirmed" by the swarm at n=4. Scripted as `canary/redteam/swarm_probes.py`, run on 40 judge + 100 dev seeds per tier: below the solver in every cell (judge: +0.742 / +0.648 / +0.363 vs +0.765 / +0.671 / +0.545), honest elimination play. The flag was an audit false positive: the posterior-based "justified" check does not credit hard elimination. Added as battery row `swarm_w2b008` (paired one-sided rule) and EXPLOITS #50. Difficulty note forwarded: on easy and medium this no-Bayes heuristic is statistically tied with the solver.
- **S5 flake fixed** (EXPLOITS #51): a plus probe "beat" the solver by abstaining after the solver's wrong last-day accusation. The rule now counts only seeds where the plus episode accepted the accusation; an abstaining plus episode must score exactly 0; full runs need mean ≤ solver + 0.05. Deterministic regression test on medium 900000 under the public secret.
- **Battery regenerated** after rebasing onto justSilas 0f379cd: all probes blocked; replay 959 of 969 (47,586 steps, 0 differ; the 140 v1.4 gemini-4-carbon episodes now replay-verified); Harbor 37 of 37.
- **Tests:** `tests/test_anticheat.py` + `tests/test_harbor_ledger_sig.py`: 120 passed. The full local `make test` was stopped twice: once deliberately (stale tree mid-edit), and once at about 66% by Claude Code's low-memory reaper, with no failures up to that point. The full suite runs in the PR's CI.
- **Facts checked from files:** cheat_probe 0.0 × 6 (`signature=ok`, 149 attempts, `"holes": []`); signed cheat −1.0 × 6; tamper negative control: forged `score: 1.0` → reward 0, `FAIL: bad ledger signature`; isolation OK in 31/31 trials that ran solve.sh; swarm 35 whitebox + 16 blackbox = 51 attackers, 0 exploits, 1,789 tool calls, positive control 4/4.
- **Residual risks** (documented, not changed after the freeze): sidecar holds `GEMINI_API_KEY`; `check_leak_feed` spends daily budget; published retired keys cannot catch re-signed forgeries.

### 01:40 gate: expert tier (justSilas-expert)

Pending.

### ~07:00: `afterquery-final` judge-protocol hunt

Pending.
