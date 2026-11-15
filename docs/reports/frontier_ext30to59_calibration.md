# v1.4 Hard Extension (Seeds 30-59): Posterior Calibration, Break-Even Margin, and Stopping-Time Audit

## 1. Scope, Non-Primary Headline Rule, and Provenance

This report audits exact Bayesian posterior calibration, moving break-even expected-value margins `P* = 1 / (1 + V)`, and stopping-time shortfall decomposition across replay-verified `v1.4` `hard` cohorts for `opencode:google/gemini-4-carbon` and the deterministic reference `solver`. Every metric below is computed offline with `0` API calls by [`scripts/analyze_ext30to59_calibration.py`](../../scripts/analyze_ext30to59_calibration.py) using [`scripts/verify_replay.py`](../../scripts/verify_replay.py), [`canary/analysis/accuse.py`](../../canary/analysis/accuse.py) (`audit_episode`), [`canary/solver/regret.py`](../../canary/solver/regret.py) (`attribute`), and [`canary/analysis/tags.py`](../../canary/analysis/tags.py), and verified byte-for-byte in [`tests/test_ext30to59_calibration.py`](../../tests/test_ext30to59_calibration.py).

### Non-primary caveat (primary `0-29` headline unchanged)

- **Authoritative `v1.4` `hard` headline (`n=30`, seeds `0-29`) remains unchanged:** `+0.322 +/- 0.199` vs reference solver `+0.499 +/- 0.119` (paired diff `-0.177 +/- 0.194`), giving **`65% [24%, 98%]`** raw (`64.6%`) and **`72% [52%, 91%]`** luck-adjusted (`72.0%`, `+0.360` vs `+0.499`) in [`data/runs/committed/v1.4/paired_table_gemini.md`](../../data/runs/committed/v1.4/paired_table_gemini.md), [`docs/reports/gap.md`](gap.md), and [`docs/reports/failure_analysis_v1.4.md`](failure_analysis_v1.4.md).
- **Why `30-59` extension cohorts remain non-primary and exploratory:** Only `8/30` planned extension seeds (`[30, 34, 37, 42, 45, 48, 57, 58]`) completed valid replay-verified OpenCode episodes before shared `gemini-4-carbon` provider-quota cutoffs, leaving `22/30` seeds unobserved. Per the pre-registered extension rule in [`docs/reports/gap.md`](gap.md), incomplete extension shards (`ext8`, `fleet7`) and pooled `n=38` views (`pooled38`) diagnose agent stopping mechanics without replacing the complete `n=30` `0-29` headline.

### Input artifacts, dual layout compatibility, and Seed 34 G1 precedence

- **Reference solver (`n=60`, seeds `0-59`):** [`data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl) (`0-19`), [`data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl) (`20-29`), and [`data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl) (`30-59`).
- **Gemini primary (`n=30`, seeds `0-29`):** [`data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl).
- **Gemini extension (`ext8` `n=8` `[30, 34, 37, 42, 45, 48, 57, 58]` and `fleet7` `n=7` `[30, 34, 42, 45, 48, 57, 58]`):** loaded from [`data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl) (supporting both the `justSilas` `G1` `n=2` `[34, 37]` layout and the PR #3 `v14-runs` `n=8` deduplicated layout) together with `results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl` (`fleet7`). On overlapping seed `34`, committed `G1` precedence holds in `ext8` and `pooled38`: `G1` (`day 5`, `51` steps, `V = 0.790`, `P = 0.979`, raw `+0.790`, luck-adjusted `+0.752`, regret `0.0365`) takes precedence over `fleet7` (`day 8`, `83` steps, `V = 0.820`, `P = 0.650`, raw `+0.820`, luck-adjusted `+0.183`, regret `0.5903`), while `fleet7` retains the Fleet Seed `34` episode so both stopping behaviors are audited transparently.

## 2. Posterior Calibration (`Brier Score` and `4-Bin Reliability`) on Accused Episodes

For each accused episode, `P_accused` is the exact `SolverPolicy` Bayesian posterior over the agent's own tool observations at the `accuse` step ([`canary/analysis/accuse.py`](../../canary/analysis/accuse.py)). Brier score is `(P_accused - correct)^2`, expected wrong accusations equal `sum(1 - P_accused)`, and 4-bin Expected Calibration Error (`ECE`) partitions accused episodes across the four decision-relevant posterior regimes from [`docs/reports/failure_analysis_v1.4.md`](failure_analysis_v1.4.md) and [`docs/reports/reference_optimality.md`](reference_optimality.md): `< 0.60` (flagged `premature_accusation`), `[0.60, 0.85)` (clears fixed `0.60` audit bar, below solver's `0.85` `hard` threshold), `[0.85, 0.95)` (above solver threshold), and `[0.95, 1.00]` (singleton isolation up to the disclosed `5%` canary fingerprint flip rate).

### Table 2A: Posterior calibration summary on accused episodes

| Cohort | `n` (`acc` / `abst`) | Mean `P(acc)` | Empirical acc (`ok/acc`) | Calib. gap (`acc - P`) | Expected vs realized wrong | Brier score | 4-bin `ECE` |
|---|---|---:|---|---:|---|---:|---:|
| Gemini primary (seeds 0-29, authoritative) | `30` (`29/1`) | `0.882` | `86.2%` (`25/29`) | `-0.020` | `3.43` vs `4` | `0.1303` | `0.1045` |
| Gemini committed G1 pre-stop ([34, 37]) | `2` (`2/0`) | `0.980` | `100.0%` (`2/2`) | `+0.020` | `0.04` vs `0` | `0.0004` | `0.0200` |
| Gemini deduplicated extension (ext8) | `8` (`8/0`) | `0.951` | `100.0%` (`8/8`) | `+0.049` | `0.40` vs `0` | `0.0034` | `0.0494` |
| Gemini fleet replication shard (fleet7) | `7` (`7/0`) | `0.899` | `100.0%` (`7/7`) | `+0.101` | `0.70` vs `0` | `0.0213` | `0.1007` |
| Gemini pooled observed (0-29 + ext8) | `38` (`37/1`) | `0.897` | `89.2%` (`33/37`) | `-0.005` | `3.82` vs `4` | `0.1029` | `0.0857` |
| Reference solver primary (seeds 0-29) | `30` (`30/0`) | `0.965` | `96.7%` (`29/30`) | `+0.002` | `1.05` vs `1` | `0.0275` | `0.0307` |
| Reference solver extension (seeds 30-59) | `30` (`29/1`) | `0.962` | `93.1%` (`27/29`) | `-0.031` | `1.10` vs `2` | `0.0557` | `0.0540` |
| Reference solver full pool (seeds 0-59) | `60` (`59/1`) | `0.964` | `94.9%` (`56/59`) | `-0.015` | `2.14` vs `3` | `0.0413` | `0.0422` |
| Reference solver matched ext8 ([30..58]) | `8` (`8/0`) | `0.939` | `87.5%` (`7/8`) | `-0.064` | `0.49` vs `1` | `0.0950` | `0.0923` |

### Table 2B: Four-bin reliability breakdown (`count (mean P / empirical acc)`)

| Cohort | Accused `n` | `[0.00, 0.60)` | `[0.60, 0.85)` | `[0.85, 0.95)` | `[0.95, 1.00]` |
|---|---:|---|---|---|---|
| Gemini primary (seeds 0-29, authoritative) | `29` | `2` (`0.481` / `100.0%`) | `8` (`0.764` / `75.0%`) | `3` (`0.936` / `100.0%`) | `16` (`0.981` / `87.5%`) |
| Gemini committed G1 pre-stop ([34, 37]) | `2` | `0` (-) | `0` (-) | `0` (-) | `2` (`0.980` / `100.0%`) |
| Gemini deduplicated extension (ext8) | `8` | `0` (-) | `0` (-) | `3` (`0.911` / `100.0%`) | `5` (`0.974` / `100.0%`) |
| Gemini fleet replication shard (fleet7) | `7` | `0` (-) | `1` (`0.650` / `100.0%`) | `3` (`0.911` / `100.0%`) | `3` (`0.971` / `100.0%`) |
| Gemini pooled observed (0-29 + ext8) | `37` | `2` (`0.481` / `100.0%`) | `8` (`0.764` / `75.0%`) | `6` (`0.924` / `100.0%`) | `21` (`0.979` / `90.5%`) |
| Reference solver primary (seeds 0-29) | `30` | `0` (-) | `0` (-) | `6` (`0.906` / `83.3%`) | `24` (`0.980` / `100.0%`) |
| Reference solver extension (seeds 30-59) | `29` | `0` (-) | `0` (-) | `9` (`0.915` / `77.8%`) | `20` (`0.983` / `100.0%`) |
| Reference solver full pool (seeds 0-59) | `59` | `0` (-) | `0` (-) | `15` (`0.911` / `80.0%`) | `44` (`0.981` / `100.0%`) |
| Reference solver matched ext8 ([30..58]) | `8` | `0` (-) | `0` (-) | `4` (`0.906` / `75.0%`) | `4` (`0.971` / `100.0%`) |

### Calibration findings

1. **Reference solver posterior is tightly calibrated across `0-59` (`n=60`, `59` accused):** Mean `P(accused)` is `0.964` against `94.9%` empirical accuracy (`56/59`, expected wrong `2.14` vs `3` realized on seeds `15, 30, 32`), with Brier score `0.0413` and `0/59` accusations below `0.85` (`44/44 = 100.0%` correct in `[0.95, 1.00]`, `12/15 = 80.0%` in `[0.85, 0.95)`).
2. **Aggregate Bayesian posteriors predict Gemini's realized error count, while Brier exposes thin-evidence bets:** On `0-29` (`29` accused), `sum(1 - P)` predicts `3.43` wrong accusations vs `4` realized (and `3.82` expected vs `4` realized across `pooled38`'s `37` accusations). However, `10/29` primary accusations sit below `0.85` (`2` in `< 0.60`, `8` in `[0.60, 0.85)`), lifting Gemini's primary Brier score to `0.1303` vs `0.0275` for the `0-29` solver.
3. **`ext8` (`8/8` >= `0.908`) vs `fleet7` (`1/7` at `0.650`):** Every deduplicated `ext8` episode cleared `P >= 0.908` (`3` in `[0.85, 0.95)`, `5` in `[0.95, 1.00]`, Brier `0.0034`), whereas `fleet7` includes Fleet Seed `34`'s premature day-8 commitment (`P = 0.650` in `[0.60, 0.85)`), which raises `fleet7` Brier from `0.0034` to `0.0213`.

## 3. Moving Break-Even Bar `P* = 1 / (1 + V)` and EV Safety Margin `P_accused - P*`

Because abstaining at day `21` yields `0.000` while a wrong accusation scores `-1.000`, accusing at company value `V` has positive expected value if and only if `P_accused * V - (1 - P_accused) > 0`, i.e., `P_accused > P* = 1 / (1 + V)` (see [`docs/reports/failure_gallery_breakeven.md`](failure_gallery_breakeven.md)). The EV safety margin `P_accused - P*` links directly to the luck-adjusted score via the exact identity `luck_adj = (1 + V) * (P_accused - P*)`.

### Table 3A: Break-even threshold `P*` and EV safety margin across cohorts

| Cohort | Accused `n` | Mean `V` (acc) | Mean `P* = 1/(1+V)` | Mean margin `P - P*` | Median margin | Min margin (`seed`) | `P < 0.85` count | Neg-EV `P < P*` (`seeds`) | Neg-EV `sum(luck_adj)` |
|---|---:|---:|---:|---:|---:|---|---:|---|---:|
| Gemini primary (seeds 0-29, authoritative) | `29` | `0.545` | `0.654` | `+0.227` | `+0.278` | `-0.361` (`s23`) | `10/29` | `3/29` (`[5, 18, 23]`) | `-0.937` |
| Gemini committed G1 pre-stop ([34, 37]) | `2` | `0.745` | `0.573` | `+0.407` | `+0.407` | `+0.393` (`s37`) | `0/2` | `0/2` (`none`) | `+0.000` |
| Gemini deduplicated extension (ext8) | `8` | `0.642` | `0.611` | `+0.340` | `+0.338` | `+0.260` (`s30`) | `0/8` | `0/8` (`none`) | `+0.000` |
| Gemini fleet replication shard (fleet7) | `7` | `0.639` | `0.612` | `+0.287` | `+0.295` | `+0.101` (`s34`) | `1/7` | `0/7` (`none`) | `+0.000` |
| Gemini pooled observed (0-29 + ext8) | `37` | `0.566` | `0.645` | `+0.252` | `+0.295` | `-0.361` (`s23`) | `10/37` | `3/37` (`[5, 18, 23]`) | `-0.937` |
| Reference solver primary (seeds 0-29) | `30` | `0.554` | `0.653` | `+0.313` | `+0.341` | `+0.116` (`s10`) | `0/30` | `0/30` (`none`) | `+0.000` |
| Reference solver extension (seeds 30-59) | `29` | `0.621` | `0.620` | `+0.342` | `+0.354` | `+0.128` (`s30`) | `0/29` | `0/29` (`none`) | `+0.000` |
| Reference solver full pool (seeds 0-59) | `59` | `0.587` | `0.637` | `+0.327` | `+0.346` | `+0.116` (`s10`) | `0/59` | `0/59` (`none`) | `+0.000` |
| Reference solver matched ext8 ([30..58]) | `8` | `0.546` | `0.651` | `+0.288` | `+0.286` | `+0.128` (`s30`) | `0/8` | `0/8` (`none`) | `+0.000` |

### Break-even safety findings

1. **Primary `0-29` (`3/29` negative-EV gambles) vs `ext8` (`0/8`) and `fleet7` (`0/7`):** On `0-29`, Gemini took `3` negative-EV horizon gambles (`seeds 5, 18, 23`, margins `-0.352`, `-0.058`, `-0.361`), costing `-0.937 V` in cumulative luck-adjusted value relative to abstaining (`0.000`). Across `ext8` (`0/8` negative-EV, tightest margin `+0.260` on `seed 30`) and `fleet7` (`0/7` negative-EV, tightest margin `+0.101` on `seed 34`), every completed accusation cleared `P* = 1 / (1 + V)`.
2. **Why `P > P*` is necessary but not sufficient for optimal stopping (Fleet Seed 34):** On Fleet Seed `34` (`day 8`, `V = 0.820`), `P* = 1 / 1.820 = 0.549`, so accusing at `P = 0.650` had a positive static margin over abstaining (`+0.101`, `luck_adj = +0.183`). Yet with `13` days remaining, planting one splitting canary across the `7` Research suspects carried far higher continuation value (`Q_continue = 0.758` vs `Q_accuse = 0.183`), incurring `0.5750 V` of `accuse` regret in [`canary/solver/regret.py`](../../canary/solver/regret.py).
3. **Zero negative-EV shots across all `59` accused solver episodes (`0-59`):** The reference solver's tightest break-even margin is `+0.116` on `seed 10` in `0-29` and `+0.128` on `seed 30` in `30-59`.

## 4. Stopping-Time Shortfall Decomposition (`1.0 - luck_adj`) and Per-Decision Regret

On every accused episode, luck-adjusted score satisfies the exact identity `luck_adj = P_accused * V - (1 - P_accused) = 1.0 - (1.0 - V) - (1.0 - P_accused) * (1.0 + V)`. Thus the shortfall from the `1.000` zero-damage ceiling decomposes without residual into **value-decay cost** `(1.0 - V) = 0.05 * leaks + 0.01 * canaries + restrict_cost` (the price of waiting and probing) plus **posterior-uncertainty cost** `(1.0 - P_accused) * (1.0 + V)` (the expected penalty from committing before `P = 1`). Across all `n` cohort seeds (counting abstentions at `luck_adj = 0.0`), `1.0 - mean(luck_adj)` equals `all_seed_decay_cost + all_seed_uncertainty_cost + all_seed_abstention_cost`.

### Table 4A: Shortfall vs `1.0` and `attribute()` regret decomposition across cohorts

| Cohort | `n` (`acc`) | Accused `V`-decay `1-V` (`leak` / `can` / `rest`) | Accused `P`-uncert `(1-P)(1+V)` (`share`) | Accused `luck_adj` | All-seed shortfall (`decay + uncert + abst`) | All-seed `luck_adj` (`raw`) | Mean regret (`accuse` / `canary` / `rest`) |
|---|---|---:|---:|---:|---|---:|---|
| Gemini primary (seeds 0-29, authoritative) | `30` (`29`) | `0.455` (`0.367` / `0.083` / `0.004`) | `0.173` (`27.6%`) | `+0.372` | `0.640` (`0.440 + 0.167 + 0.033`) | `+0.360` (`+0.322`) | `0.1714` (`0.1332` / `0.0343` / `0.0039`) |
| Gemini committed G1 pre-stop ([34, 37]) | `2` (`2`) | `0.255` (`0.200` / `0.055` / `0.000`) | `0.035` (`12.1%`) | `+0.710` | `0.290` (`0.255 + 0.035 + 0.000`) | `+0.710` (`+0.745`) | `0.0413` (`0.0168` / `0.0245` / `0.0000`) |
| Gemini deduplicated extension (ext8) | `8` (`8`) | `0.358` (`0.300` / `0.058` / `0.000`) | `0.079` (`18.2%`) | `+0.563` | `0.437` (`0.358 + 0.079 + 0.000`) | `+0.563` (`+0.642`) | `0.0821` (`0.0600` / `0.0221` / `0.0000`) |
| Gemini fleet replication shard (fleet7) | `7` (`7`) | `0.361` (`0.307` / `0.054` / `0.000`) | `0.172` (`32.2%`) | `+0.467` | `0.533` (`0.361 + 0.172 + 0.000`) | `+0.467` (`+0.639`) | `0.1664` (`0.1459` / `0.0204` / `0.0000`) |
| Gemini pooled observed (0-29 + ext8) | `38` (`37`) | `0.434` (`0.353` / `0.078` / `0.003`) | `0.153` (`26.1%`) | `+0.413` | `0.598` (`0.422 + 0.149 + 0.026`) | `+0.402` (`+0.390`) | `0.1526` (`0.1178` / `0.0317` / `0.0031`) |
| Reference solver primary (seeds 0-29) | `30` (`30`) | `0.446` (`0.305` / `0.141` / `0.000`) | `0.054` (`10.9%`) | `+0.499` | `0.501` (`0.446 + 0.054 + 0.000`) | `+0.499` (`+0.499`) | `0.0733` (`0.0418` / `0.0316` / `0.0000`) |
| Reference solver extension (seeds 30-59) | `30` (`29`) | `0.379` (`0.262` / `0.117` / `0.000`) | `0.060` (`13.7%`) | `+0.561` | `0.458` (`0.367 + 0.058 + 0.033`) | `+0.542` (`+0.498`) | `0.0665` (`0.0443` / `0.0222` / `0.0000`) |
| Reference solver full pool (seeds 0-59) | `60` (`59`) | `0.413` (`0.284` / `0.129` / `0.000`) | `0.057` (`12.2%`) | `+0.529` | `0.479` (`0.407 + 0.056 + 0.017`) | `+0.521` (`+0.498`) | `0.0699` (`0.0430` / `0.0269` / `0.0000`) |
| Reference solver matched ext8 ([30..58]) | `8` (`8`) | `0.454` (`0.319` / `0.135` / `0.000`) | `0.094` (`17.1%`) | `+0.453` | `0.547` (`0.454 + 0.094 + 0.000`) | `+0.453` (`+0.375`) | `0.1073` (`0.0766` / `0.0307` / `0.0000`) |

### Table 4B: Same-seed paired gap decomposition (`Gemini` vs matched `solver`)

| Paired cohort | `n` | Raw ratio [95% CI] | Luck-adj. ratio [95% CI] | `Solver - Gem` luck-adj. gap | Excess `V`-decay (`Gem - Sol`) | Excess `P`-uncert (`Gem - Sol`) | Excess abst (`Gem - Sol`) | Brier (`Gem` vs `Sol`) | Mean regret (`Gem` vs `Sol`) |
|---|---:|---|---|---:|---:|---:|---:|---|---|
| Primary headline (seeds 0-29, authoritative) | `30` | `64.6%` `[24%, 98%]` | **`72.0%`** `[52%, 91%]` | `+0.140` | `-0.007` | `+0.113` | `+0.033` | `0.1303` vs `0.0275` | `0.1714` vs `0.0733` |
| Deduplicated extension (ext8, G1 Seed 34 precedence) | `8` | `171.3%` `[107%, 485%]` | **`124.4%`** `[109%, 150%]` | `-0.110` | `-0.096` | `-0.014` | `+0.000` | `0.0034` vs `0.0950` | `0.0821` vs `0.1073` |
| Fleet replication shard (fleet7, Fleet Seed 34) | `7` | `200.4%` `[116%, 837%]` | **`109.4%`** `[70%, 155%]` | `-0.040` | `-0.124` | `+0.084` | `+0.000` | `0.0213` vs `0.1078` | `0.1664` vs `0.1042` |
| Exploratory pooled observed (0-29 + ext8) | `38` | `82.4%` `[47%, 122%]` | **`82.2%`** `[64%, 100%]` | `+0.087` | `-0.026` | `+0.086` | `+0.026` | `0.1029` vs `0.0417` | `0.1526` vs `0.0805` |

### Stopping-time and regret takeaways

1. **Posterior-uncertainty cost, not net `V` decay, explains the primary `0-29` and `pooled38` frontier gap:** On `0-29`, Gemini's accused value-decay cost (`0.455`) nearly matches the solver's (`0.446`) because planting fewer canaries (`0.083` vs `0.141`) offsets extra leak damage from slower identification (`0.367` vs `0.305`). Instead, `P`-uncertainty cost `(1 - P)(1 + V)` is **3.1x larger** per seed (`0.167` vs `0.054`, excess `+0.113 V/seed`), and remains `+0.086 V/seed` across `pooled38` (`82.2%` `[64%, 100%]` luck-adjusted).
2. **Why `ext8` (`124.4%` luck-adjusted) outperforms `fleet7` (`109.4%` luck-adjusted):** Both `ext8` and `fleet7` save `~0.10-0.12 V/seed` in `V` decay relative to the matched solver by planting `5.75` and `5.43` canaries vs `13.50` and `13.71`. On `fleet7`, Fleet Seed `34` (`P = 0.650`) injects `0.637 V` of posterior-uncertainty cost, pushing Gemini's mean uncertainty cost nearly **2x above** the solver (`0.172` vs `0.088`). Replacing Fleet Seed `34` with committed G1 Seed `34` (`P = 0.979`, uncertainty cost `0.038 V`) cuts `ext8` uncertainty cost in half (`0.079` vs `0.094`).
3. **`attribute()` confirms stopping-time regret dominates step-level loss:** Across `0-29`, `77.7%` of Gemini's `0.1714 V/ep` regret occurs at `accuse` (`0.1332 V/ep` premature commitment vs `0.0000 V/ep` at `advance_day` hesitation). That same `accuse`-step dominance holds on `fleet7` (`87.7%`), `ext8` (`73.1%`), and `pooled38` (`77.2%`).

## 5. Per-Seed Extension Calibration, Break-Even, and Shortfall Table (`ext8` + `Fleet 34` + Matched `Solver`)

| Seed | Cohort role | Day (`steps`) | `Can` / `Int` / `Leaks` | `V` | `P(acc)` | `P*` | Margin `P - P*` | `V`-decay `1-V` | `P`-uncert `(1-P)(1+V)` | `luck_adj` (`raw`) | Brier | Regret (`accuse`) |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 30 | `gemini_fleet_in_ext8` | `d11` (`112`) | `6` / `61` / `8` | `0.540` | `0.909` | `0.649` | `+0.260` | `0.460` | `0.140` | `+0.400` (`+0.540`) | `0.0083` | `0.1286` (`0.1188`) |
| 34 | `gemini_g1_in_ext8` | `d5` (`51`) | `6` / `26` / `3` | `0.790` | `0.979` | `0.559` | `+0.420` | `0.210` | `0.038` | `+0.752` (`+0.790`) | `0.0004` | `0.0365` (`0.0177`) |
| 34 | `gemini_fleet34_in_fleet7` | `d8` (`83`) | `3` / `49` / `3` | `0.820` | `0.650` | `0.549` | `+0.101` | `0.180` | `0.637` | `+0.183` (`+0.820`) | `0.1225` | `0.5903` (`0.5750`) |
| 37 | `gemini_g1_in_ext8` | `d6` (`64`) | `5` / `32` / `5` | `0.700` | `0.981` | `0.588` | `+0.393` | `0.300` | `0.032` | `+0.668` (`+0.700`) | `0.0004` | `0.0460` (`0.0158`) |
| 42 | `gemini_fleet_in_ext8` | `d12` (`74`) | `8` / `16` / `7` | `0.570` | `0.969` | `0.637` | `+0.332` | `0.430` | `0.049` | `+0.521` (`+0.570`) | `0.0010` | `0.0520` (`0.0341`) |
| 45 | `gemini_fleet_in_ext8` | `d16` (`156`) | `6` / `88` / `7` | `0.590` | `0.973` | `0.629` | `+0.344` | `0.410` | `0.043` | `+0.547` (`+0.590`) | `0.0007` | `0.0407` (`0.0269`) |
| 48 | `gemini_fleet_in_ext8` | `d13` (`135`) | `4` / `79` / `7` | `0.610` | `0.916` | `0.621` | `+0.295` | `0.390` | `0.135` | `+0.475` (`+0.610`) | `0.0071` | `0.1308` (`0.1100`) |
| 57 | `gemini_fleet_in_ext8` | `d8` (`76`) | `4` / `38` / `4` | `0.760` | `0.970` | `0.568` | `+0.402` | `0.240` | `0.053` | `+0.707` (`+0.760`) | `0.0009` | `0.0510` (`0.0334`) |
| 58 | `gemini_fleet_in_ext8` | `d11` (`111`) | `7` / `61` / `7` | `0.580` | `0.908` | `0.633` | `+0.275` | `0.420` | `0.145` | `+0.435` (`+0.580`) | `0.0085` | `0.1712` (`0.1234`) |
| 30 | `solver_ext8_matched` | `d18` (`138`) | `23` / `0` / `8` | `0.370` | `0.858` | `0.730` | `+0.128` | `0.630` | `0.195` | `+0.175` (`-1.000`) | `0.7362` | `0.2124` (`0.1711`) |
| 34 | `solver_ext8_matched` | `d6` (`53`) | `10` / `0` / `4` | `0.700` | `0.978` | `0.588` | `+0.390` | `0.300` | `0.037` | `+0.663` (`+0.700`) | `0.0005` | `0.0463` (`0.0194`) |
| 37 | `solver_ext8_matched` | `d5` (`45`) | `8` / `0` / `3` | `0.770` | `0.924` | `0.565` | `+0.359` | `0.230` | `0.135` | `+0.635` (`+0.770`) | `0.0058` | `0.1286` (`0.1096`) |
| 42 | `solver_ext8_matched` | `d10` (`81`) | `14` / `0` / `7` | `0.510` | `0.997` | `0.662` | `+0.335` | `0.490` | `0.005` | `+0.505` (`+0.510`) | `0.0000` | `0.0094` (`0.0000`) |
| 45 | `solver_ext8_matched` | `d11` (`87`) | `16` / `0` / `7` | `0.490` | `0.955` | `0.671` | `+0.284` | `0.510` | `0.067` | `+0.423` (`+0.490`) | `0.0020` | `0.1156` (`0.0509`) |
| 48 | `solver_ext8_matched` | `d9` (`75`) | `14` / `0` / `8` | `0.460` | `0.955` | `0.685` | `+0.270` | `0.540` | `0.066` | `+0.394` (`+0.460`) | `0.0020` | `0.0988` (`0.0510`) |
| 57 | `solver_ext8_matched` | `d8` (`66`) | `11` / `0` / `7` | `0.540` | `0.899` | `0.649` | `+0.250` | `0.460` | `0.156` | `+0.384` (`+0.540`) | `0.0102` | `0.1739` (`0.1378`) |
| 58 | `solver_ext8_matched` | `d9` (`73`) | `12` / `0` / `7` | `0.530` | `0.942` | `0.654` | `+0.288` | `0.470` | `0.089` | `+0.441` (`+0.530`) | `0.0034` | `0.0732` (`0.0732`) |

## 6. Keyless Reproduction Commands

```bash
CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/analyze_ext30to59_calibration.py --check
CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/analyze_ext30to59_calibration.py --json
CANARY_ALLOW_DEV=1 PYTHONPATH=. pytest -q tests/test_ext30to59_calibration.py
```
