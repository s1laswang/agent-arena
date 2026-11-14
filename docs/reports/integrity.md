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
