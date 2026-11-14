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
