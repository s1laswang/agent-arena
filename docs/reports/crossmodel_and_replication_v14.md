# Canary v1.4 Cross-Model Comparison and Seeds 30-59 Replication Audit

Generated deterministically offline (`0` live LLM calls, single-process) by:
```bash
python scripts/eval_replication_and_crossmodel.py
python scripts/eval_replication_and_crossmodel.py --check
```

## Data Rule and Replay Integrity

- Rules version verified: `v1.4` (`Env(tier, seed)` step-by-step replay tolerance `1e-09`).
- Total episode records inspected and replay-verified: `875/875` valid (`0` rejected by DATA RULE).
- Fleet shard wall-clock guard: `wall_s < 3590s` (`rc != timeout`, `end_reason != error`, `valid != False`).
- Pre-registered primary `0-29` clean completions exceeding 3590s (run prior to the fleet 3600s cap, motivating Harbor's `3600s -> 10800s` bump in commit `512836b9`): `6` episodes, all `rc=0` and replay-exact.
- Paired bootstrap: `10000` resamples over shared seeds (`seed=0`).

## Part A: Primary Evaluation (`seeds 0-29`, Pre-Registered Headline Scope)

Seeds 0-29 per tier (pre-registered Sat 14 Nov ~22:45 Helsinki, commit 671ed96, docs/reports/gap.md) form the sole primary headline result.

### Medium Tier (`seeds 0-29`, `n=30` paired per cohort)

| tier | cohort | n | score +/- 95% CI | / solver [95% CI] | paired diff [95% CI] | acc | accused | day | mean P(acc) | luck-adj | luck-adj / solver [95% CI] | gambles | luck |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| medium | `opencode-gemini-4-carbon` | 30 | +0.713 +/- 0.042 | 110.5% [99.3%, 127.0%] | +0.068 [-0.005, +0.152] | 1.00 | 1.00 | 8.0 | 0.96 | +0.652 | 101.1% [85.3%, 118.6%] | 2/30 (7%) | +0.061 |
| medium | `inproc-gemini-4-carbon` | 30 | +0.530 +/- 0.138 | 82.2% [56.4%, 107.6%] | -0.115 [-0.295, +0.044] | 0.83 | 0.87 | 9.0 | 0.93 | +0.479 | 74.3% [51.7%, 99.1%] | 3/30 (10%) | +0.051 |
| medium | `opencode-gemini-3.5-flash` | 30 | +0.434 +/- 0.236 | 67.3% [29.4%, 103.3%] | -0.211 [-0.469, +0.020] | 0.83 | 1.00 | 9.0 | 0.87 | +0.485 | 75.2% [44.9%, 105.4%] | 6/30 (20%) | -0.051 |
| medium | `solver` | 30 | +0.645 +/- 0.087 | 100% | 0.000 | 0.90 | 0.90 | 7.6 | 1.00 | +0.645 | 100% | 0/30 (0%) | +0.000 |
| medium | `grok_tactics` | 30 | +0.460 +/- 0.123 | 71.3% [50.9%, 94.5%] | -0.185 [-0.334, -0.032] | 0.70 | 0.70 | 7.7 | 1.00 | +0.460 | 71.3% [50.9%, 94.5%] | 0/30 (0%) | +0.000 |
| medium | `heuristic` | 30 | -0.407 +/- 0.284 | -63.1% [-107.0%, -19.2%] | -1.052 [-1.343, -0.749] | 0.37 | 1.00 | 11.3 | 0.59 | -0.064 | -9.9% [-35.7%, 17.6%] | 21/30 (70%) | -0.343 |
| medium | `logs_only` | 30 | -1.000 +/- 0.000 | -155.0% [-181.1%, -138.4%] | -1.645 [-1.723, -1.552] | 0.00 | 1.00 | 10.0 | 0.01 | -0.983 | -152.3% [-178.2%, -135.7%] | 30/30 (100%) | -0.017 |
| medium | `do_nothing` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.645 [-0.723, -0.552] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
| medium | `stop_early` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.645 [-0.723, -0.552] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
| medium | `guess_day1` | 30 | -0.933 +/- 0.131 | -144.7% [-174.9%, -117.9%] | -1.578 [-1.710, -1.402] | 0.03 | 1.00 | 1.0 | 0.05 | -0.900 | -139.5% [-162.9%, -124.5%] | 30/30 (100%) | -0.033 |

### Hard Tier (`seeds 0-29`, `n=30` paired per cohort)

| tier | cohort | n | score +/- 95% CI | / solver [95% CI] | paired diff [95% CI] | acc | accused | day | mean P(acc) | luck-adj | luck-adj / solver [95% CI] | gambles | luck |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hard | `opencode-gemini-4-carbon` | 30 | +0.322 +/- 0.199 | 64.6% [23.8%, 98.3%] | -0.177 [-0.384, -0.008] | 0.83 | 0.97 | 13.2 | 0.88 | +0.360 | 72.0% [51.7%, 91.2%] | 3/30 (10%) | -0.037 |
| hard | `inproc-gemini-4-carbon` | 30 | +0.473 +/- 0.118 | 94.8% [62.2%, 140.0%] | -0.026 [-0.213, +0.155] | 0.93 | 0.97 | 12.7 | 0.93 | +0.421 | 84.3% [65.0%, 105.8%] | 3/30 (10%) | +0.052 |
| hard | `opencode-gemini-3.5-flash` | 30 | +0.373 +/- 0.177 | 74.7% [35.9%, 122.8%] | -0.126 [-0.347, +0.091] | 0.90 | 1.00 | 12.7 | 0.71 | +0.110 | 22.0% [-22.6%, 63.2%] | 10/30 (33%) | +0.263 |
| hard | `solver` | 30 | +0.499 +/- 0.119 | 100% | 0.000 | 0.97 | 1.00 | 10.6 | 0.97 | +0.499 | 100% | 0/30 (0%) | -0.000 |
| hard | `grok_tactics` | 30 | +0.432 +/- 0.085 | 86.5% [66.8%, 119.3%] | -0.067 [-0.186, +0.075] | 0.93 | 0.93 | 10.4 | 0.96 | +0.384 | 77.0% [61.0%, 94.6%] | 0/30 (0%) | +0.047 |
| hard | `heuristic` | 30 | +0.086 +/- 0.204 | 17.2% [-25.8%, 59.7%] | -0.413 [-0.666, -0.171] | 0.80 | 1.00 | 14.4 | 0.78 | +0.052 | 10.5% [-20.2%, 37.4%] | 6/30 (20%) | +0.033 |
| hard | `logs_only` | 30 | -1.000 +/- 0.000 | -200.4% [-270.8%, -167.0%] | -1.499 [-1.599, -1.369] | 0.00 | 1.00 | 10.0 | 0.01 | -0.979 | -196.1% [-225.4%, -174.6%] | 30/30 (100%) | -0.021 |
| hard | `do_nothing` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.499 [-0.599, -0.369] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
| hard | `stop_early` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.499 [-0.599, -0.369] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
| hard | `guess_day1` | 30 | -1.000 +/- 0.000 | -200.4% [-270.8%, -167.0%] | -1.499 [-1.599, -1.369] | 0.00 | 1.00 | 1.0 | 0.03 | -0.950 | -190.3% [-218.5%, -169.3%] | 30/30 (100%) | -0.050 |

### Head-to-Head Cross-Model Comparison (`opencode-gemini-4-carbon` minus `opencode-gemini-3.5-flash`)

| tier | n | carbon raw | flash raw | paired raw diff [95% CI] | carbon luck-adj | flash luck-adj | paired luck-adj diff [95% CI] | carbon gambles (lucky) | flash gambles (lucky) | flash minus carbon luck |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| medium | 30 | +0.713 | +0.434 | +0.279 [+0.072, +0.519] | +0.652 | +0.485 | +0.167 [-0.006, +0.358] | 2/30 (2) | 6/30 (1) | -0.112 |
| hard | 30 | +0.322 | +0.373 | -0.051 [-0.290, +0.182] | +0.360 | +0.110 | +0.250 [+0.038, +0.475] | 3/30 (2) | 10/30 (7) | +0.300 |

### Why `gemini-3.5-flash` Hard Raw Score (`74.7% [35.9%, 122.8%]`) Collapses Under Luck Adjustment (`22.0% [-22.6%, 63.2%]`)

1. **Unjustified sub-breakeven gambling (`0%` abstention)**: On `hard` seeds `0-29`, `opencode-gemini-3.5-flash` never abstains (`accused_rate = 1.00`) and accuses at mean solver posterior `P(accused) = 0.71` vs `opencode-gemini-4-carbon`'s `P(accused) = 0.88`. In `10/30` episodes (`33.3%`, seeds `[0, 2, 3, 10, 17, 18, 21, 23, 26, 27]`), `gemini-3.5-flash` accuses below the public EV break-even threshold `1 / (1 + shown_V)`, compared to `3/30` (`10.0%`) for `gemini-4-carbon`.
2. **Realized luck windfall**: Across those `10` negative-EV gambles, `gemini-3.5-flash` hit the true mole on `7/10` episodes (`0.90` overall accuracy), generating `realized_luck = +0.263` per episode vs `-0.037` for `gemini-4-carbon` (a `+0.300` per-episode luck swing).
3. **Decision-quality reversal**: Scoring each accusation by its exact solver-posterior expected value `P * V - (1 - P)` drops `gemini-3.5-flash` from `+0.373` (`74.7% [35.9%, 122.8%]`) to `+0.110` (`22.0% [-22.6%, 63.2%]` of solver), while `gemini-4-carbon` rises to `+0.360` (`72.0% [51.7%, 91.2%]` of solver), giving `gemini-4-carbon` a `+0.250` (`[+0.038, +0.475]`) paired luck-adjusted advantage on `hard` alongside a `+0.167` (`[-0.006, +0.358]`) paired luck-adjusted advantage on `medium` (`n=30`).
4. **Concordance on `hard` (`n=30`)**: Accuracy concordance is `both_correct=23`, `carbon_only=2`, `flash_only=4`, `neither=1`; sub-breakeven gamble concordance is `both_gamble=2`, `carbon_only=1`, `flash_only=8`, `neither=19`.

## Part B: Hard Replication Audit (`seeds 30-59`, Strictly Separated from Headline)

Seeds 30-59 extension/replication shards are reported (a) strictly separately on their own and (b) pooled with seeds 0-29 as a secondary sensitivity check only, never replacing the primary n=30 row (commits 671ed96 and f9fb7a4a, docs/reports/gap.md).

### Replication Cohort (`opencode-gemini-4-carbon` on Completed Seeds `[30, 34, 42, 45, 57]`) and Secondary Pooled Sensitivity

| tier | cohort | n | score +/- 95% CI | / solver [95% CI] | paired diff [95% CI] | acc | accused | day | mean P(acc) | luck-adj | luck-adj / solver [95% CI] | gambles | luck |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hard | `opencode-gemini-4-carbon-replication` | 5 | +0.656 +/- 0.110 | 264.5% [115.4%, 304.0%] | +0.408 [+0.088, +0.980] | 1.00 | 1.00 | 11.0 | 0.89 | +0.472 | 109.6% [57.7%, 179.0%] | 0/5 (0%) | +0.184 |
| hard | `opencode-gemini-4-carbon-pooled-sensitivity` | 35 | +0.370 +/- 0.175 | 79.9% [41.6%, 124.4%] | -0.093 [-0.290, +0.090] | 0.86 | 0.97 | 12.9 | 0.88 | +0.376 | 76.7% [57.7%, 95.9%] | 3/35 (9%) | -0.006 |

| seed | carbon score | carbon day | carbon P(acc) | carbon luck-adj | solver score | solver day | solver luck-adj |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | +0.540 | 11 | 0.909 | +0.400 | -1.000 | 18 | +0.175 |
| 34 | +0.820 | 8 | 0.650 | +0.183 | +0.700 | 6 | +0.663 |
| 42 | +0.570 | 12 | 0.969 | +0.521 | +0.510 | 10 | +0.505 |
| 45 | +0.590 | 16 | 0.973 | +0.547 | +0.490 | 11 | +0.423 |
| 57 | +0.760 | 8 | 0.970 | +0.707 | +0.540 | 8 | +0.384 |

Note on small-sample replication ratio (`n=5`): on seed `30` the reference solver suffered a 5% canary fingerprint flip (`score = -1.000`, `luck_adjusted = +0.175`), depressing the 5-seed raw solver denominator to `+0.248` (vs `+0.498` across all 30 seeds `30-59`). Under the secondary pooled sensitivity check (`n=35`), the luck-adjusted ratio is `76.7% [57.7%, 95.9%]` (95% CI upper bound `< 100%`). Per pre-registration (`docs/reports/gap.md`), `primary_0_29` (`n=30`) remains the sole headline.

### Reference Baselines on Hard Seeds `30-59` (`n=30` Each, Post-PR16 Verification)

- Post-PR16 zero-reward invariants on `30-59`: `stop_early == 0.0` (`all_zero=True`, `mean=+0.000`), `do_nothing == 0.0` (`all_zero=True`, `mean=+0.000`).

| tier | cohort | n | score +/- 95% CI | / solver [95% CI] | paired diff [95% CI] | acc | accused | day | mean P(acc) | luck-adj | luck-adj / solver [95% CI] | gambles | luck |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| hard | `solver` | 30 | +0.498 +/- 0.156 | 100% | 0.000 | 0.90 | 0.97 | 8.4 | 0.96 | +0.542 | 100% | 0/30 (0%) | -0.044 |
| hard | `grok_tactics` | 30 | +0.314 +/- 0.126 | 63.1% [34.5%, 106.2%] | -0.184 [-0.373, +0.022] | 0.83 | 0.87 | 11.1 | 0.97 | +0.321 | 59.2% [44.4%, 75.3%] | 0/30 (0%) | -0.006 |
| hard | `heuristic` | 30 | +0.118 +/- 0.163 | 23.6% [-11.0%, 59.9%] | -0.380 [-0.602, -0.153] | 0.87 | 1.00 | 15.6 | 0.82 | +0.062 | 11.4% [-12.9%, 32.3%] | 6/30 (20%) | +0.056 |
| hard | `logs_only` | 30 | -0.942 +/- 0.114 | -189.1% [-291.5%, -140.9%] | -1.440 [-1.599, -1.243] | 0.03 | 1.00 | 10.0 | 0.01 | -0.983 | -181.4% [-206.2%, -163.9%] | 30/30 (100%) | +0.041 |
| hard | `random` | 30 | -0.833 +/- 0.136 | -167.3% [-250.3%, -126.5%] | -1.331 [-1.531, -1.089] | 0.00 | 0.83 | 6.2 | 0.03 | -0.791 | -146.0% [-175.7%, -118.1%] | 25/30 (83%) | -0.042 |
| hard | `restrict_all` | 30 | -1.000 +/- 0.000 | -200.8% [-306.1%, -158.7%] | -1.498 [-1.630, -1.327] | 0.00 | 1.00 | 9.0 | 0.01 | -0.993 | -183.3% [-208.4%, -165.8%] | 30/30 (100%) | -0.007 |
| hard | `guess_day1` | 30 | -1.000 +/- 0.000 | -200.8% [-306.1%, -158.7%] | -1.498 [-1.630, -1.327] | 0.00 | 1.00 | 1.0 | 0.03 | -0.950 | -175.3% [-199.1%, -158.6%] | 30/30 (100%) | -0.050 |
| hard | `stop_early` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.498 [-0.630, -0.327] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
| hard | `do_nothing` | 30 | +0.000 +/- 0.000 | 0.0% [0.0%, 0.0%] | -0.498 [-0.630, -0.327] | 0.00 | 0.00 | n/a | n/a | +0.000 | 0.0% [0.0%, 0.0%] | 0/30 (0%) | +0.000 |
