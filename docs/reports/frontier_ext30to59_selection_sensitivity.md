# v1.4 Hard Extension (Seeds 30-59): Partial-Completion Selection and Sensitivity Audit

## 1. Scope, Non-Primary Headline Rule, and Provenance

This report audits partial-completion selection bias and bounds full-cohort `n=60` (`0-59`) outcomes for `opencode:google/gemini-4-carbon` on rules `v1.4` `hard`, directly testing the quota-truncation caveat documented in [`docs/reports/gap.md`](gap.md) ("Under quota pressure, episodes that complete may be the shorter ones"). Every number in this report is computed deterministically with `0` API calls by [`scripts/analyze_ext30to59_selection.py`](../../scripts/analyze_ext30to59_selection.py) and verified in [`tests/test_ext30to59_selection_sensitivity.py`](../../tests/test_ext30to59_selection_sensitivity.py).

### Non-primary caveat (primary `0-29` headline unchanged)

- **Authoritative `v1.4` `hard` headline (`n=30`, seeds `0-29`) is unchanged:** `+0.322 +/- 0.199` vs reference solver `+0.499 +/- 0.119` (paired diff `-0.177 +/- 0.194`), giving **`65% [24%, 98%]`** raw (`64.6%`) and **`72% [52%, 91%]`** luck-adjusted (`72.0%`, `+0.360` vs `+0.499`) in [`data/runs/committed/v1.4/paired_table_gemini.md`](../../data/runs/committed/v1.4/paired_table_gemini.md) and [`docs/reports/failure_analysis_v1.4.md`](failure_analysis_v1.4.md).
- **Why `30-59` remains exploratory:** Only `8/30` extension seeds (`[30, 34, 37, 42, 45, 48, 57, 58]`) completed valid replay-verified OpenCode episodes before shared `gemini-4-carbon` quota cutoffs, leaving `22/30` seeds (`[31, 32, 33, 35, 36, 38, 39, 40, 41, 43, 44, 46, 47, 49, 50, 51, 52, 53, 54, 55, 56, 59]`) unobserved. Per the pre-registered extension rule in [`docs/reports/gap.md`](gap.md), incomplete extension shards never replace the `n=30` primary row.

### Input files and Seed 34 G1 precedence

- **Reference solver (`n=60`, seeds `0-59`):** [`data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl) (`0-19`), [`data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl) (`20-29`), and [`data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl) (`30-59`).
- **Gemini primary (`n=30`, seeds `0-29`):** [`data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl).
- **Gemini extension (`n=8` deduplicated seeds `[30, 34, 37, 42, 45, 48, 57, 58]`):** combined from [`data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl) (`G1` seeds `[34, 37]` on `justSilas`, or all `8` deduplicated seeds when PR #3 `v14-runs` is merged) and [`results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl) (`7` fleet seeds `[30, 34, 42, 45, 48, 57, 58]`). On overlapping seed `34`, committed `G1` precedence holds (`day 5`, `51` steps, raw `+0.790`, luck-adjusted `+0.752` kept over fleet `day 8`, `83` steps, raw `+0.820`, luck-adjusted `+0.183`; trajectory comparison in [`docs/reports/frontier_ext30to59_trajectories.md`](frontier_ext30to59_trajectories.md)).

## 2. Selection Audit on Seeds 30-59: Observed 8 vs Unobserved 22 on Solver Observables

Because the deterministic reference solver ran to completion on all `30` seeds `30-59` (`0` missing episodes), its per-seed observables measure intrinsic world difficulty and investigation duration without missingness. Luck-adjusted scores (`P*V - (1-P)` on accused episodes, `0.0` on abstentions) are computed via [`canary/analysis/accuse.py`](../../canary/analysis/accuse.py).

### Table 2A: Reference solver observables across extension and baseline cohorts

| Solver cohort | `n` | Raw score +/- 95% CI | Luck-adj. +/- 95% CI | Mean accuse day (accused) | Mean horizon day (all) | Mean steps +/- 95% CI (median) | Mean canaries +/- 95% CI | Accuracy (`ok/n`) | Abstain / wrong |
|---|---:|---|---|---:|---:|---|---|---|---:|
| Initial G1 pre-stop seeds ([34, 37]) | 2 | `+0.735 +/- 0.069` | `+0.649 +/- 0.027` | `5.50` (`2`) | `5.50` | `49.00 +/- 7.84` (`49.0`) | `9.00 +/- 1.96` | `100.0%` (`2/2`) | `0` / `0` |
| G1 unobserved seeds (28 seeds) | 28 | `+0.481 +/- 0.166` | `+0.534 +/- 0.065` | `8.63` (`27`) | `9.07` | `73.29 +/- 9.77` (`72.5`) | `12.39 +/- 1.58` | `89.3%` (`25/28`) | `1` / `2` |
| Observed extension seeds (ext8) | 8 | `+0.375 +/- 0.392` | `+0.453 +/- 0.107` | `9.50` (`8`) | `9.50` | `77.25 +/- 19.56` (`74.0`) | `13.50 +/- 3.19` | `87.5%` (`7/8`) | `0` / `1` |
| Unobserved extension seeds (unobs22) | 22 | `+0.543 +/- 0.161` | `+0.574 +/- 0.071` | `8.00` (`21`) | `8.59` | `69.64 +/- 10.79` (`65.5`) | `11.68 +/- 1.70` | `90.9%` (`20/22`) | `1` / `1` |
| Full extension cohort (seeds 30-59) | 30 | `+0.498 +/- 0.156` | `+0.542 +/- 0.062` | `8.41` (`29`) | `8.83` | `71.67 +/- 9.38` (`69.0`) | `12.17 +/- 1.51` | `90.0%` (`27/30`) | `1` / `2` |
| Primary cohort (seeds 0-29) | 30 | `+0.499 +/- 0.119` | `+0.499 +/- 0.064` | `10.60` (`30`) | `10.60` | `84.27 +/- 11.58` (`72.0`) | `14.13 +/- 1.84` | `96.7%` (`29/30`) | `0` / `1` |
| Full pooled cohort (seeds 0-59) | 60 | `+0.498 +/- 0.097` | `+0.521 +/- 0.044` | `9.53` (`59`) | `9.72` | `77.97 +/- 7.56` (`72.0`) | `13.15 +/- 1.21` | `93.3%` (`56/60`) | `1` / `3` |

### Table 2B: Two-sample balance test (`ext8` `n=8` minus `unobs22` `n=22`, 10,000 permutations, `rng_seed=0`)

| Solver observable | Observed `ext8` (`n=8`) | Unobserved `unobs22` (`n=22`) | Diff (`obs8 - unobs22`) | Two-sided permutation `p` |
|---|---:|---:|---:|---:|
| Raw score | `0.375` | `0.543` | `-0.168` | `0.3974` |
| Luck-adjusted score (`P*V - (1-P)`) | `0.453` | `0.574` | `-0.121` | `0.0886` |
| Accuse day (accused episodes: `8` vs `21`) | `9.50` | `8.00` | `+1.50` | `0.2376` |
| Horizon day (all episodes, abstention = `21`) | `9.50` | `8.59` | `+0.91` | `0.6081` |
| Total solver steps | `77.25` | `69.64` | `+7.61` | `0.5141` |
| Canaries planted | `13.50` | `11.68` | `+1.82` | `0.3181` |
| Company value `V` at end | `0.546` | `0.629` | `-0.082` | `0.1609` |
| Solver accuracy | `0.875` | `0.909` | `-0.034` | `1.0000` |
| Solver abstention rate | `0.000` | `0.045` | `-0.045` | `1.0000` |

### Findings on the `gap.md` quota-truncation caveat

1. **Why the caveat held sharply on `justSilas` `G1` (`n=2`, seeds `[34, 37]`):** Under single-bucket sequential execution in `G1` (where `31` attempts hit `infra:provider_quota`), the two completed worlds (`34` and `37`) averaged `49.0` solver steps and day `5.5` (solver raw `+0.735`). Across all `C(30, 2) = 435` seed pairs in `30-59`, only `30/435` (`6.9%`) are at or below `49.0` solver steps (and `30/435` = `6.9%` at or below day `5.5`), directly confirming Silas's duration-selection warning for `n=2`.
2. **How the 6 fleet shard-head seeds changed world-level balance in `ext8` (`n=8`):** Because the fleet run partitioned `30-59` into parallel worker seed ranges (`[30, 42, 45, 48, 57, 58]` completed at shard heads), the combined `8` observed seeds are slightly *longer* and *harder* for the solver than the `22` unobserved seeds: `77.25` vs `69.64` steps (`+7.61`, `p = 0.5141`), accuse day `9.50` vs `8.00` (`+1.50`, `p = 0.2376`), canaries `13.50` vs `11.68`, and solver luck-adjusted score `+0.453` vs `+0.574` (`-0.121`, `p = 0.0886`).
3. **Why sensitivity bounds are still required (`22/30` missing):** World-level solver balance does not rule out agent-side truncation within fixed seeds (e.g., an interview-heavy Gemini trajectory hitting provider quota on a seed the solver finishes quickly), nor does `n=8` (`100.0%` Gemini accuracy, `+0.642` raw, `+0.563` luck-adjusted vs `+0.322` raw, `+0.360` luck-adjusted on `0-29`) eliminate small-sample variance. Moreover, the sole solver abstention in `30-59` (`seed 38`: `157` solver steps, day `21`, `25` canaries, `V = 0.200`) and one solver wrong accusation (`seed 32`: `-1.000` raw, `+0.535` luck-adjusted) sit in the `22` unobserved seeds.

## 3. Primary `0-29` Solver-Duration Strata Used for Imputation

On the complete `0-29` primary cohort (`n=30`), median solver step count is `72.0` steps and median solver accuse/horizon day is `9.0`:

| `0-29` stratification rule | Fast `n` / Slow `n` (`0-29`) | Fast Gemini raw / luck-adj. | Slow Gemini raw / luck-adj. | Fast solver raw / luck-adj. | Slow solver raw / luck-adj. | `unobs22` fast / slow |
|---|---|---|---:|---|---|---:|
| `solver total_steps <= 72 vs > 72` | `16` / `14` | `+0.292` / `+0.493` | `+0.357` / `+0.206` | `+0.580` / `+0.623` | `+0.406` / `+0.358` | `13` / `9` |
| `solver total_steps < 72 vs >= 72` | `13` / `17` | `+0.338` / `+0.512` | `+0.311` / `+0.243` | `+0.692` / `+0.641` | `+0.351` / `+0.391` | `12` / `10` |
| `solver horizon_day <= 9 vs > 9` | `19` / `11` | `+0.287` / `+0.424` | `+0.384` / `+0.249` | `+0.584` / `+0.614` | `+0.353` / `+0.301` | `16` / `6` |

Why luck-adjusted Gemini score drops sharply on slow-solver worlds (`+0.493` -> `+0.206` on `steps > 72`) while raw score slightly rises (`+0.292` -> `+0.357` on `steps > 72`, vs `+0.338` -> `+0.311` when boundary seed `15` at `72` steps is grouped into `steps >= 72`): on `0-29`, two disclosed 5% canary fingerprint flips (`seeds 1, 26` at `60` solver steps, `P >= 0.95`, `-1.000` raw) fell in the fast stratum while two negative-EV day-21 gambles (`seeds 5, 23` in `steps > 72`) happened to guess right (`+0.160`, `+0.230` raw vs `-0.408`, `-0.444` luck-adjusted; see [`docs/reports/failure_analysis_v1.4.md`](failure_analysis_v1.4.md)). We report both `steps > 72` (`n=14`) and `steps >= 72` (`n=17`) in Scenario 4 so neither realization quirk is hidden.

## 4. Pooled `n=60` (`0-59`) Sensitivity Scenarios and Manski Bounds

All `n=60` scenarios keep the `38` observed episodes (`0-29` primary + `8` deduplicated `ext8` seeds) fixed, pair every seed `0-59` against the exact `n=60` reference solver (`+0.498` raw [`0.4985`], `+0.521` luck-adjusted [`0.5206`]), and compute `10,000`-resample paired bootstrap 95% CIs (`rng_seed=0`, matching [`results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled38.md`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled38.md)). For empirical imputation rules (`Scenarios 2, 3a, 3b, 4a, 4b`), we also report two-stage donor-resampling bootstrap CIs (`rng_seed=0`) that draw i.i.d. `0-29` / `ext8` donors on each resampled unobserved seed so plug-in mean imputation never artificially narrows confidence intervals.

### Table 4A: Deterministic sensitivity battery (`raw` and `luck-adjusted`)

| Scenario | `n` (`obs`+`imp`) | Gemini raw | Solver raw | Raw diff | Raw ratio [95% CI] | Gemini luck-adj. | Solver luck-adj. | Luck-adj. diff | Luck-adj. ratio [95% CI] |
|---|---:|---:|---:|---:|---|---:|---:|---:|---|
| Primary headline (seeds 0-29, authoritative) | `30` (`30+0`) | `+0.322` | `+0.499` | `-0.177` | `64.6%` `[24%, 98%]` | `+0.360` | `+0.499` | `-0.140` | **`72.0%`** `[52%, 91%]` |
| Scenario 1: Observed n=38 pool (0-29 + ext8) | `38` (`38+0`) | `+0.390` | `+0.473` | `-0.083` | `82.4%` `[47%, 122%]` | `+0.402` | `+0.489` | `-0.087` | **`82.2%`** `[64%, 100%]` |
| Scenario 2: Primary-mean continuation (0-29 mean on 22 unobserved) | `60` (`38+22`) | `+0.365` | `+0.498` | `-0.133` | `73.2%` `[52%, 98%]` | `+0.387` | `+0.521` | `-0.134` | **`74.3%`** `[63%, 86%]` |
| Scenario 3a: Solver-steps-stratified imputation (median steps <= 72 vs > 72) | `60` (`38+22`) | `+0.364` | `+0.498` | `-0.135` | `72.9%` `[51%, 98%]` | `+0.393` | `+0.521` | `-0.128` | **`75.4%`** `[64%, 87%]` |
| Scenario 3b: Solver-day-stratified imputation (median day <= 9 vs > 9) | `60` (`38+22`) | `+0.362` | `+0.498` | `-0.137` | `72.6%` `[51%, 98%]` | `+0.393` | `+0.521` | `-0.128` | **`75.4%`** `[64%, 86%]` |
| Scenario 4a: Quota-truncation conservative (0-29 slow steps > 72 on all 22) | `60` (`38+22`) | `+0.378` | `+0.498` | `-0.121` | `75.8%` `[54%, 101%]` | `+0.331` | `+0.521` | `-0.190` | **`63.5%`** `[52%, 76%]` |
| Scenario 4a-alt: Quota-truncation conservative strict (0-29 steps >= 72 on all 22) | `60` (`38+22`) | `+0.361` | `+0.498` | `-0.138` | `72.4%` `[51%, 97%]` | `+0.344` | `+0.521` | `-0.177` | **`66.1%`** `[54%, 78%]` |
| Scenario 4b: Optimistic continuation (ext8 mean on all 22) | `60` (`38+22`) | `+0.482` | `+0.498` | `-0.016` | `96.8%` `[73%, 126%]` | `+0.461` | `+0.521` | `-0.059` | **`88.6%`** `[77%, 101%]` |
| Scenario 4c: Manski lower bound (abstain = 0.000 on all 22) | `60` (`38+22`) | `+0.247` | `+0.498` | `-0.252` | `49.5%` `[27%, 74%]` | `+0.255` | `+0.521` | `-0.266` | **`49.0%`** `[35%, 64%]` |
| Scenario 4d: Manski worst-case lower bound (wrong = -1.000 on all 22) | `60` (`38+22`) | `-0.120` | `+0.498` | `-0.618` | `-24.0%` `[-66%, 15%]` | `-0.112` | `+0.521` | `-0.632` | **`-21.5%`** `[-55%, 13%]` |
| Scenario 4e: Manski solver-V upper bound (V_solver(s) at P=1.0 on all 22) | `60` (`38+22`) | `+0.477` | `+0.498` | `-0.021` | `95.8%` `[72%, 124%]` | `+0.485` | `+0.521` | `-0.035` | **`93.2%`** `[82%, 104%]` |
| Scenario 4f: Manski algebraic support ceiling (V = 1.000 on all 22) | `60` (`38+22`) | `+0.614` | `+0.498` | `+0.115` | `123.1%` `[94%, 159%]` | `+0.622` | `+0.521` | `+0.101` | **`119.4%`** `[102%, 138%]` |

### Table 4B: Donor-resampling paired bootstrap 95% CIs (`rng_seed=0`, `B=10,000`) on empirical imputations

| Empirical imputation scenario (`n=60`) | Imputation law on 22 unobserved seeds | Plug-in raw ratio [95% CI] | Donor-boot raw [95% CI] | Plug-in luck-adj. ratio [95% CI] | Donor-boot luck-adj. [95% CI] |
|---|---|---|---|---|---|
| Scenario 2: Primary-mean continuation (0-29 mean on 22 unobserved) | Impute 0-29 primary mean (+0.322 raw, +0.360 luck-adj.) on all 22 unobserved seeds | `73.2%` `[52%, 98%]` | `[45%, 103%]` | `74.3%` `[63%, 86%]` | **`[60%, 89%]`** |
| Scenario 3a: Solver-steps-stratified imputation (median steps <= 72 vs > 72) | Match each unobserved seed to 0-29 fast (steps <= 72, n=16) or slow (steps > 72, n=14) stratum | `72.9%` `[51%, 98%]` | `[45%, 103%]` | `75.4%` `[64%, 87%]` | **`[62%, 88%]`** |
| Scenario 3b: Solver-day-stratified imputation (median day <= 9 vs > 9) | Match each unobserved seed to 0-29 fast (day <= 9, n=19) or slow (day > 9, n=11) stratum | `72.6%` `[51%, 98%]` | `[44%, 103%]` | `75.4%` `[64%, 86%]` | **`[62%, 89%]`** |
| Scenario 4a: Quota-truncation conservative (0-29 slow steps > 72 on all 22) | Impute 0-29 slow-solver half (steps > 72, n=14: +0.357 raw, +0.206 luck-adj.) on all 22 unobserved | `75.8%` `[54%, 101%]` | `[50%, 105%]` | `63.5%` `[52%, 76%]` | **`[48%, 79%]`** |
| Scenario 4a-alt: Quota-truncation conservative strict (0-29 steps >= 72 on all 22) | Impute 0-29 slow-or-median half (steps >= 72, n=17: +0.311 raw, +0.243 luck-adj.) on all 22 unobserved | `72.4%` `[51%, 97%]` | `[45%, 102%]` | `66.1%` `[54%, 78%]` | **`[51%, 81%]`** |
| Scenario 4b: Optimistic continuation (ext8 mean on all 22) | Impute observed ext8 mean (+0.642 raw, +0.563 luck-adj.) on all 22 unobserved seeds | `96.8%` `[73%, 126%]` | `[73%, 126%]` | `88.6%` `[77%, 101%]` | **`[76%, 101%]`** |

### Key conclusions from the sensitivity battery

1. **Every baseline and solver-stratified `n=60` continuation confirms a ~25-27% frontier shortfall:** Primary-mean continuation (`Scenario 2`: `73.2%` raw, `74.3%` luck-adjusted), solver-steps stratification (`Scenario 3a`: `72.9%` raw, `75.4%` luck-adjusted; donor-boot CI `[62%, 88%]`), and solver-day stratification (`Scenario 3b`: `72.6%` raw, `75.4%` luck-adjusted; donor-boot CI `[62%, 89%]`) all sit within `3.4` percentage points of the `0-29` luck-adjusted headline (`72.0%`) and exclude luck-adjusted parity (`100%`) under both plug-in and donor-resampling bootstrap CIs.
2. **Adversarial quota-truncation adjustment widens the luck-adjusted gap further:** If all `22` unobserved seeds behaved like the slow-solver half of `0-29` (`Scenario 4a`), pooled `n=60` luck-adjusted performance drops to **`63.5%` `[52%, 76%]`** (`steps > 72`, `-0.190` V/seed) or **`66.1%` `[54%, 78%]`** (`steps >= 72`, `72.4%` raw).
3. **Even optimistic `ext8` continuation and solver-`V` upper bounds stay below `100%` point parity:** Extrapolating `ext8`'s `8/8` streak (`+0.642` raw, `+0.563` luck-adjusted) across all `22` unobserved seeds (`Scenario 4b`) yields `96.8%` raw and `88.6%` luck-adjusted, while granting Gemini the solver's stopping `V` at `P=1.0` on every unobserved seed (`Scenario 4e`) yields `95.8%` raw and `93.2%` luck-adjusted. On the downside, Manski no-assumption bounds span `49.0%` (all-abstain `0.0`) down to `-21.5%` (all-wrong `-1.0`), with only the unachievable day-1 zero-cost `V = 1.0` algebraic support ceiling (`Scenario 4f`: `119.4%`) exceeding parity.

## 5. Complete Per-Seed Extension Table (`30-59`, `n=30`)

| Seed | Status | Solver raw | Solver luck-adj. | Solver day (`fin`) | Solver steps (`stratum`) | Solver canaries | Solver `V` | Solver `P(acc)` | Gemini raw | Gemini luck-adj. | Gemini day / steps |
|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|
| 30 | `observed_fleet` | `-1.000` | `+0.175` | `d18` (`18`) | `138` (`slow`) | `23` | `0.370` | `0.858` | `+0.540` | `+0.400` | `d11` / `112` |
| 31 | `unobserved` | `+0.520` | `+0.520` | `d9` (`9`) | `74` (`slow`) | `13` | `0.520` | `1.000` | - | - | - |
| 32 | `unobserved` | `-1.000` | `+0.535` | `d9` (`9`) | `72` (`fast`) | `11` | `0.690` | `0.908` | - | - | - |
| 33 | `unobserved` | `+0.530` | `+0.509` | `d10` (`10`) | `79` (`slow`) | `12` | `0.530` | `0.986` | - | - | - |
| 34 | `observed_g1` | `+0.700` | `+0.663` | `d6` (`6`) | `53` (`fast`) | `10` | `0.700` | `0.978` | `+0.790` | `+0.752` | `d5` / `51` |
| 35 | `unobserved` | `+0.680` | `+0.576` | `d9` (`9`) | `73` (`slow`) | `12` | `0.680` | `0.938` | - | - | - |
| 36 | `unobserved` | `+0.770` | `+0.706` | `d5` (`5`) | `45` (`fast`) | `8` | `0.770` | `0.964` | - | - | - |
| 37 | `observed_g1` | `+0.770` | `+0.635` | `d5` (`5`) | `45` (`fast`) | `8` | `0.770` | `0.924` | `+0.700` | `+0.668` | `d6` / `64` |
| 38 | `unobserved` | `+0.000` | `+0.000` | abstain (`21`) | `157` (`slow`) | `25` | `0.200` | - | - | - | - |
| 39 | `unobserved` | `+0.700` | `+0.697` | `d6` (`6`) | `53` (`fast`) | `10` | `0.700` | `0.998` | - | - | - |
| 40 | `unobserved` | `+0.550` | `+0.547` | `d8` (`8`) | `65` (`fast`) | `10` | `0.550` | `0.998` | - | - | - |
| 41 | `unobserved` | `+0.570` | `+0.562` | `d10` (`10`) | `78` (`slow`) | `13` | `0.570` | `0.995` | - | - | - |
| 42 | `observed_fleet` | `+0.510` | `+0.505` | `d10` (`10`) | `81` (`slow`) | `14` | `0.510` | `0.997` | `+0.570` | `+0.521` | `d12` / `74` |
| 43 | `unobserved` | `+0.690` | `+0.666` | `d8` (`8`) | `66` (`fast`) | `11` | `0.690` | `0.986` | - | - | - |
| 44 | `unobserved` | `+0.750` | `+0.647` | `d8` (`8`) | `65` (`fast`) | `10` | `0.750` | `0.941` | - | - | - |
| 45 | `observed_fleet` | `+0.490` | `+0.423` | `d11` (`11`) | `87` (`slow`) | `16` | `0.490` | `0.955` | `+0.590` | `+0.547` | `d16` / `156` |
| 46 | `unobserved` | `+0.700` | `+0.642` | `d7` (`7`) | `57` (`fast`) | `10` | `0.700` | `0.966` | - | - | - |
| 47 | `unobserved` | `+0.430` | `+0.271` | `d11` (`11`) | `88` (`slow`) | `17` | `0.430` | `0.889` | - | - | - |
| 48 | `observed_fleet` | `+0.460` | `+0.394` | `d9` (`9`) | `75` (`slow`) | `14` | `0.460` | `0.955` | `+0.610` | `+0.475` | `d13` / `135` |
| 49 | `unobserved` | `+0.800` | `+0.798` | `d6` (`6`) | `51` (`fast`) | `10` | `0.800` | `0.999` | - | - | - |
| 50 | `unobserved` | `+0.780` | `+0.780` | `d5` (`5`) | `42` (`fast`) | `7` | `0.780` | `1.000` | - | - | - |
| 51 | `unobserved` | `+0.720` | `+0.608` | `d5` (`5`) | `43` (`fast`) | `8` | `0.720` | `0.935` | - | - | - |
| 52 | `unobserved` | `+0.660` | `+0.599` | `d6` (`6`) | `52` (`fast`) | `9` | `0.660` | `0.963` | - | - | - |
| 53 | `unobserved` | `+0.620` | `+0.612` | `d9` (`9`) | `74` (`slow`) | `13` | `0.620` | `0.995` | - | - | - |
| 54 | `unobserved` | `+0.500` | `+0.479` | `d11` (`11`) | `88` (`slow`) | `15` | `0.500` | `0.986` | - | - | - |
| 55 | `unobserved` | `+0.720` | `+0.665` | `d7` (`7`) | `57` (`fast`) | `8` | `0.720` | `0.968` | - | - | - |
| 56 | `unobserved` | `+0.530` | `+0.522` | `d14` (`14`) | `108` (`slow`) | `17` | `0.530` | `0.995` | - | - | - |
| 57 | `observed_fleet` | `+0.540` | `+0.384` | `d8` (`8`) | `66` (`fast`) | `11` | `0.540` | `0.899` | `+0.760` | `+0.707` | `d8` / `76` |
| 58 | `observed_fleet` | `+0.530` | `+0.441` | `d9` (`9`) | `73` (`slow`) | `12` | `0.530` | `0.942` | `+0.580` | `+0.435` | `d11` / `111` |
| 59 | `unobserved` | `+0.720` | `+0.692` | `d5` (`5`) | `45` (`fast`) | `8` | `0.720` | `0.984` | - | - | - |

## 6. Keyless Reproduction Commands

```bash
CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/analyze_ext30to59_selection.py --check
CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/analyze_ext30to59_selection.py --json
CANARY_ALLOW_DEV=1 PYTHONPATH=. pytest -q tests/test_ext30to59_selection_sensitivity.py
```
