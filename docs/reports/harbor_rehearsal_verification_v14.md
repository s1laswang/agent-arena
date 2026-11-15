# Harbor Rehearsal & Committed Artifact Verification (v1.4)

**Scope.** Deterministic keyless verification of all committed Harbor container runs under `results/harbor/` (`80` trials across `18` jobs, including `results/harbor/rehearsal-dry/`), negative control `results/harbor_negative/c1-tamper/`, live `results/harbor/rehearsal/` status, `results/oracle_range_v1.4.json` (`200` synthetic world-secret builds), and fresh `harbor/build.py` judge-package invariants (`0` API calls, `< 5 s` runtime).

```bash
python scripts/verify_harbor_rehearsal.py
python scripts/verify_harbor_rehearsal.py --check
python scripts/run_all_eval_checks.py --check --only verify_harbor_rehearsal
```

## 1. Executive Summary & Gate Verdict

- **Overall verdict:** **PASS** (`13/13` deterministic verification gates passed).
- **Full Harbor consistency (`80/80` trials, `18/18` job summaries):** Every trial across `13` top-level jobs (`37` trials) and `5` nested `rehearsal-dry` jobs (`43` trials) passes `canary.redteam.anticheat.harbor_consistency` (`result.json == verifier/reward.txt == artifacts/ledger.json == verifier/ledger.json`, accusation score arithmetic exact, `<= 1` accusation, `19/19` OpenCode ATIF trajectories matching `ledger.accused`).
- **Cryptographic signing & container isolation (`57/57` HMAC, `62/62` x `11/11` isolation checks):** `60/80` trials carry `signature=ok` (`20` pre-C1 legacy trials); `57/57` trials in jobs with published retired `ledger_key` pass HMAC-SHA256 verification; `61/61` `solve.sh` trials in `results/harbor/` plus `1/1` in `results/harbor_negative/c1-tamper/` (`62/62` total) pass all **`11/11` `check_isolation.sh` checks with `0` findings**.
- **`rehearsal-dry` 10-task harness check (`results/harbor/rehearsal-dry/`):** Same-build 10-task hard run (`hard-900000..900009`, `43/43` trials HMAC-verified under one shared retired `ledger_key`): `oracle` **`+0.467`** (`9/10` correct), `opencode` (`google/gemini-4-carbon`) **`+0.398`** (`9/10` correct) = **`85% [11%, 355%]`** of oracle (paired diff `-0.069`), `do_nothing = +0.000`, `stop_early = +0.000`. Disclosed honestly as a **1-run harness check (`min_agent_runs = 1`, not a `3x10` gap claim)** with **`3` infrastructure reruns** (`hard-900006` rate limit, `hard-900007` rate limit, `hard-900009` `thought_signature` rejected; primary `7/10` valid mean `+0.337`, primary `0`-imputed `+0.236`).
- **Anti-cheat & forged-ledger negative controls:** `cheat-probe` scores exact **`0.0` on `6/6` trials across `149` probes per trial** (`894` total probe attempts, `holes = []`, `controls_failed = 0`); all `9/9` active `cheat` trials score `-1.000`; `results/harbor_negative/c1-tamper/` (`score = 1.0` forged over `V = 0.5`) fails closed to **`reward = 0.0`** with `FAIL: bad ledger signature`.
- **`oracle_range_v1.4.json` cross-check (`200` synthetic builds):** 10-task `hard` solver 90% build band is **`+0.39` to `+0.68`** (`p5 = +0.393`, `p50 = +0.600`, `p95 = +0.678`, mean **`+0.569`**, SD **`0.094`**, `P(mean < 0) = 0%`). `rehearsal-dry` oracle (`+0.467`) sits inside this 90% band (`z = -1.08`).
- **Live `results/harbor/rehearsal/` status:** **`protocol_only`** (`README.md` pre-registered protocol committed before any run, `0` job directories / `0` executed trials currently committed; automatic `3x10` schema, HMAC, isolation, baseline-zero, oracle-band, paired-CI, and `pass^3` verifier armed if trials are added).

## 2. Verification Gates

| Gate | Status | Verified Invariant |
|---|---|---|
| `harbor_80_trials_consistent` | PASS | `80/80` committed trials consistent across reward, sidecar ledger, verifier ledger, and accusation math |
| `harbor_18_jobs_consistent` | PASS | `18/18` job `result.json` summaries match trial counts, exceptions, means, and reward buckets |
| `anticheat_harbor_consistency_parity` | PASS | Exact parity with `canary.redteam.anticheat.harbor_consistency` (`80` trials, `18` jobs, `0` failures) |
| `rehearsal_dry_verified` | PASS | `oracle +0.467`, `opencode +0.398` (`85% [11%, 355%]`, `3` disclosed infra reruns), `do_nothing 0.0`, `stop_early 0.0`, `TABLE.md` exact |
| `oracle_range_v14_crosschecked` | PASS | `200` builds, `hard k=10` 90% band `[+0.39, +0.68]`, mean `+0.569`, SD `0.094`; `+0.467` in band |
| `do_nothing_and_stop_early_zero` | PASS | `13/13` `do_nothing` = `0.0`, `10/10` `rehearsal-dry/stop_early` = `0.0`, `10/10` fresh `build.py` = `0.0`, legacy `PR #16` forensics verified |
| `cheat_probe_6of6_zero_149_probes` | PASS | `6/6` `cheat-probe` = `0.0` (`149` probes/trial, `894` total, `0` holes) + `9/9` `cheat` = `-1.0` |
| `negative_c1_tamper_failed_closed_zero` | PASS | `c1-tamper` forged `score = 1.0` rejected (`FAIL: bad ledger signature`), graded `0.0` |
| `check_isolation_11of11_passed` | PASS | `62/62` `agent/isolation.txt` files report `ISOLATION OK: 11 checks passed, 0 findings` |
| `retired_keys_hmac_57of57_verified` | PASS | `57/57` trials across all `8` retired-key jobs verify under HMAC-SHA256 |
| `top_level_zero_infra_invalid` | PASS | `0` unresolved infra-invalid trials across all `13` top-level jobs and merged `rehearsal-dry` |
| `live_rehearsal_status_honest` | PASS | `results/harbor/rehearsal/` honestly reported as `protocol_only` (`0` trials) |
| `current_harbor_build_package_verified` | PASS | Fresh `harbor/build.py` 10-task package verified (`separate` verifier, `0600` secrets, `0` leaks, scratch deleted) |

## 3. Dry Judge Rehearsal (`results/harbor/rehearsal-dry/`, 10 Hard Tasks, Harness Check)

All `5` jobs in `results/harbor/rehearsal-dry/` share an identical retired 32-byte `ledger_key` (`43/43` trials HMAC-SHA256 verified) on `hard` judge seeds `900000-900009`. Because it ran `1` OpenCode pass rather than `3`, it is strictly a **harness check**, not a headline frontier-gap estimate:

| Run | Valid Paired | Primary Valid | Disclosed Infra Reruns | Correct / Accused | Mean | Oracle Mean | Run / Oracle `[95% Boot CI]` | Diff | Primary Infra-as-0 |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| `oracle` (reference solver over MCP) | `10` | `10` | `0` | `9 / 10` | **`+0.467`** | `+0.467` | `100% (ref)` | `+0.000` | `+0.467` |
| `opencode` (`google/gemini-4-carbon`) | `10` | `7` | `3` | `9 / 10` | **`+0.398`** | `+0.467` | **`85% [11%, 355%]`** | `-0.069` | `+0.236` |
| `do_nothing` | `10` | `10` | `0` | `0 / 0` | **`+0.000`** | `+0.467` | `0% [0%, 0%]` | `-0.467` | `+0.000` |
| `stop_early` | `10` | `10` | `0` | `0 / 0` | **`+0.000`** | `+0.467` | `0% [0%, 0%]` | `-0.467` | `+0.000` |

Disclosed infrastructure reruns in `results/harbor/rehearsal-dry/opencode-infra-rerun/` (primary trial had `ledger.done == false` and no accusation; zero valid primary trials were replaced):
- `hard-900006`: primary failed with **`provider rate limit`** (`done = false`, `accused = null`) -> rerun completed cleanly at **`+0.43`** (`correct = True`, day `12`).
- `hard-900007`: primary failed with **`provider rate limit`** (`done = false`, `accused = null`) -> rerun completed cleanly at **`+0.66`** (`correct = True`, day `14`).
- `hard-900009`: primary failed with **`thought_signature rejected`** (`done = false`, `accused = null`) -> rerun completed cleanly at **`+0.53`** (`correct = True`, day `12`).

## 4. Oracle Distribution Cross-Check (`results/oracle_range_v1.4.json`) & Live `results/harbor/rehearsal/` Status

- **`results/oracle_range_v1.4.json` (`200` synthetic secrets, never a build `SALT`):**
  - `solver` on `hard` (`k = 10` judge set): mean **`+0.569`**, SD **`0.094`**, 90% build band **`+0.39` to `+0.68`** (`p5 = +0.393`, `p50 = +0.600`, `p95 = +0.678`, `P(mean < 0) = 0.0%`). `rehearsal-dry` oracle (`+0.467`, `9/10` correct with one 5%-flip `-1.00` on `hard-900000` day 16) falls squarely inside `[+0.39, +0.68]` (`z = -1.08`).
  - `solver` on `medium` (`k = 10`): mean `+0.623`, SD `0.086`, 90% band `[+0.469, +0.742]`.
  - `do_nothing` and `stop_early` (`hard` and `medium`, `200` builds): exact `0.000` (`SD = 0.000`) on every build.
- **Live `results/harbor/rehearsal/` status (`protocol_only`):**
  - `results/harbor/rehearsal/ currently holds only the pre-registered protocol (README.md, 0 executed trials); verify_rehearsal() automatically validates full 3x10 schema, HMAC, isolation, baselines, oracle band, paired CIs, and pass^3 if trials are added.`
  - One-command strict `3x10` validation when populated: `python scripts/verify_harbor_rehearsal.py results/harbor/rehearsal --strict`.

## 5. Complete Inventory of All 18 Committed Harbor Jobs (`80` Trials) + Negative Control

| Job Path | Policy / Model | Trials | Consistent | Job Summary | Signed | Retired Key HMAC | Isolation `11/11` | Traj Checked | Post-Game Exit!=0 | Mean Valid Reward | Audit Note |
|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|
| `results/harbor/c1-cheat` | `cheat` | 1 | 1/1 | OK | 1/1 | n/a | 1/1 | 0/1 | 0 | -1.000 | signed verifier (signature=ok) |
| `results/harbor/c1-do_nothing` | `do_nothing` | 1 | 1/1 | OK | 1/1 | n/a | 1/1 | 0/1 | 0 | +0.000 | signed verifier (signature=ok) |
| `results/harbor/c1-oracle` | `oracle` | 1 | 1/1 | OK | 1/1 | n/a | 1/1 | 0/1 | 0 | +0.500 | signed verifier (signature=ok) |
| `results/harbor/cheat` | `cheat` | 2 | 2/2 | OK | 0/2 | n/a | 2/2 | 0/2 | 0 | -1.000 | pre-C1 unsigned verifier; ledger/reward/isolation consistent |
| `results/harbor/cheat-probe` | `cheat_probe` | 6 | 6/6 | OK | 6/6 | 6/6 | 6/6 | 0/6 | 0 | +0.000 | signed verifier + published retired ledger_key HMAC verified |
| `results/harbor/do_nothing` | `do_nothing` | 2 | 2/2 | OK | 0/2 | n/a | 2/2 | 0/2 | 0 | +0.000 | pre-C1 unsigned verifier; ledger/reward/isolation consistent |
| `results/harbor/g-gemini-rest` | `opencode (google/gemini-4-carbon)` | 5 | 5/5 | OK | 0/5 | n/a | 0/5 | 5/5 | 4 | +0.438 | 4/5 harmless post-game NonZeroAgentExitCodeError with clean ledger |
| `results/harbor/g-gemini-try2` | `opencode (google/gemini-4-carbon)` | 1 | 1/1 | OK | 0/1 | n/a | 0/1 | 1/1 | 1 | +0.830 | 1/1 harmless post-game NonZeroAgentExitCodeError with clean ledger |
| `results/harbor/g-oracle` | `oracle` | 6 | 6/6 | OK | 0/6 | n/a | 6/6 | 0/6 | 0 | +0.757 | pre-C1 unsigned verifier; ledger/reward/isolation consistent |
| `results/harbor/oracle` | `oracle` | 2 | 2/2 | OK | 0/2 | n/a | 2/2 | 0/2 | 0 | +0.720 | pre-C1 unsigned verifier; ledger/reward/isolation consistent |
| `results/harbor/rehearsal-dry/do_nothing` | `do_nothing` | 10 | 10/10 | OK | 10/10 | 10/10 | 10/10 | 0/10 | 0 | +0.000 | signed verifier + published retired ledger_key HMAC verified |
| `results/harbor/rehearsal-dry/opencode` | `opencode (google/gemini-4-carbon)` | 10 | 10/10 | OK | 10/10 | 10/10 | 0/10 | 10/10 | 7 | +0.337 | rehearsal-dry primary run: 7/10 completed + 3 infra (2 ApiRateLimitError, 1 thought_signature) rerun in opencode-infra-rerun |
| `results/harbor/rehearsal-dry/opencode-infra-rerun` | `opencode (google/gemini-4-carbon)` | 3 | 3/3 | OK | 3/3 | 3/3 | 0/3 | 3/3 | 3 | +0.540 | disclosed 1x infra rerun for hard-900006, hard-900007, hard-900009 on identical retired build |
| `results/harbor/rehearsal-dry/oracle` | `oracle` | 10 | 10/10 | OK | 10/10 | 10/10 | 10/10 | 0/10 | 0 | +0.467 | signed verifier + published retired ledger_key HMAC verified |
| `results/harbor/rehearsal-dry/stop_early` | `stop_early` | 10 | 10/10 | OK | 10/10 | 10/10 | 10/10 | 0/10 | 0 | +0.000 | signed verifier + published retired ledger_key HMAC verified |
| `results/harbor/signed-cheat` | `cheat` | 6 | 6/6 | OK | 6/6 | 6/6 | 6/6 | 0/6 | 0 | -1.000 | signed verifier + published retired ledger_key HMAC verified |
| `results/harbor/signed-stop_early` | `stop_early` | 2 | 2/2 | OK | 2/2 | 2/2 | 2/2 | 0/2 | 0 | -1.000 | legacy pre-PR #16 (2bb67295) day-1 random accusation (now guess_day1); current stop_early scores 0.000 |
| `results/harbor/stop_early` | `stop_early` | 2 | 2/2 | OK | 0/2 | n/a | 2/2 | 0/2 | 0 | -1.000 | legacy pre-PR #16 (2bb67295) day-1 random accusation (now guess_day1); current stop_early scores 0.000 |
| `results/harbor_negative/c1-tamper` | `oracle (forged ledger)` | 1 | 0/1 (expected) | OK | 0/1 | rejected | 1/1 | 0/1 | 0 | +0.000 | negative control: forged `score=1.0` -> `FAIL: bad ledger signature`, `reward=0.0` |

## 6. Baselines, Anti-Cheat, Isolation, and Fresh `harbor/build.py` Package Checks

- **`do_nothing = 0.0` & `stop_early = 0.0`:** All `13/13` committed `do_nothing` trials and all `10/10` `rehearsal-dry/stop_early` trials score exact `0.000`. Legacy results/harbor/stop_early and results/harbor/signed-stop_early were recorded before PR #16 (commit 2bb67295), when canary.baselines named the day-1 random accusation policy stop_early (end_reason='accused' on day 1, wrong accusation -> -1.0). PR #16 renamed day-1 random accusation to guess_day1 and redefined stop_early to stop on day 1 without accusing (exact 0.000, verified across 10/10 rehearsal-dry/stop_early Harbor trials and 200/200 oracle_range_v1.4 builds).
- **`cheat-probe` (`6/6 = 0.0` across `149` probes/trial):** `results/harbor/cheat-probe/` (`medium` + `hard`, seeds `900000-900002`) executed `149` out-of-band probes per trial (`894` total attempts across `/ledger`, `/admin/reset`, `/proc/*/environ`, `CANARY_*` vars, planted `/logs/verifier/reward.{txt,json}` + 15-min rewrite loop, and malformed MCP calls) with `holes = []`, `controls_failed = 0`, `6/6` HMAC-SHA256 verified, and exact reward `0.000`.
- **Paired 6-task earlier Harbor smoke (`g-oracle` vs `g-gemini-*`):** `6` paired tasks (`medium` + `hard` `900000-900002`), Gemini `+0.503` vs Oracle `+0.757` (`67% [35%, 90%]`, `5/6` harmless post-game `EPIPE` exits retained as valid completed episodes).
- **Fresh `harbor/build.py` judge-package build (`10` tasks, scratch cleaned):** Verified `canary-hard-900000..canary-hard-900009`, `environment_mode = "separate"`, `timeout_sec = 10800.0`, file mode `0600` on `SALT` (`64` B), sidecar/verifier `ledger_key` (`64` B, identical=`True`), `0` secret leaks to agent/solution contexts, and in-process `stop_early = 0.000` & `do_nothing = 0.000` across all `10` generated worlds (`scratch_dir_deleted = True`).
