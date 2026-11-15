# Canary v1.4 Bayes Stopping-Rule Counterfactual and Two-Term Gap Decomposition

Synced to `justSilas@5f9b3297` across the replay-verified 777-episode v1.4 corpus (`472` committed + `305` FR8 replication; pure CPU, zero live API calls). Primary `0-29` cohorts carry post-hoc lock `671ed96` (28 s after `8fd4dec`); OpenCode `gpt-5.5` hard `0-29` was pre-registered at `cf394894` (results `ca0a0dc0`); `gemini-4-carbon` hard `30-59` dedup union `[30, 34, 37, 42, 45, 57]` (`n=6`) applies committed G1 (`f9fb7a4a`, seeds `[34, 37]`) precedence over FR8 replication (`[30, 34, 42, 45, 57]`). Harbor judge-path rehearsal on `d0ead011` finished at `93%, 116%, 131%` of oracle across `[10, 10, 9]` valid trials.

## Key Findings

1. **Primary OpenCode `gemini-4-carbon` hard (`0-29`) is dominated by evidence-collection deficit, not premature stopping:** Only `3/30` episodes (`seeds [5, 18, 23]`) accused below Bayes break-even `P(accused) < 1/(1+V)`. Replacing negative-EV gambles with `0.0` abstention lifts raw score from `+0.322` (`64.6%`) to `+0.343` (`68.7%`) and luck-adjusted EV from `+0.360` (`72.0%`) to `+0.391` (`78.3%`). **77.7%** (`+0.109` of `+0.140`) of the luck-adjusted gap and **88.5%** (`+0.156` of `+0.177`) of the raw gap come from weaker evidence gathering.
2. **FR8 OpenCode `gemini-3.5-flash` medium (`0-29`) is primarily a stopping-rule failure:** `6/30` episodes (`seeds [8, 11, 13, 22, 26, 29]`, 5 wrong `-1.00`) gambled below break-even on days 13-14. The Bayes abstention gate recovers `+0.095` luck-adjusted EV (**59.4%** of the gap) and `+0.146` raw score (**69.1%** of the raw gap), lifting Flash medium to `+0.580` (`89.9%` of solver).
3. **OpenCode `gpt-5.5` hard (`0-29`) exhibits well-calibrated stopping (`0/28` sub-breakeven under observable `V_known`, `1/28` marginal `-0.064` EV on seed `5` under latent `V_true=0.41`):** Its `+0.082` luck-adjusted shortfall vs solver is driven by clean `rc=0` non-accuse exits on seeds `[0, 17]`, where terminal `P(top)` already reached `0.949` and `0.963` (`+0.042` cohort-mean EV foregone; `92.0%` of solver if executed).
4. **Reference solver sanity check:** Both `solver` medium (`0-29`, abstaining on seeds `[20, 21, 29]`) and `solver` hard (`0-29`) record `0/30` sub-breakeven accusations (`0.000` stopping loss).

## (a) Bayes Break-Even Abstention Counterfactual (`P(accused) >= 1/(1+V)`)

| Cohort | n | Accused | Sub-BE (seeds) | Raw -> BE Raw (/ solver) | Luck -> BE Luck (/ solver) |
|---|---:|---:|---|---|---|
| OpenCode gemini-4-carbon medium (0-29) | 30 | 30/30 | 2 ([7, 29]) | +0.713 -> +0.681 (110.5% -> 105.5%) | +0.652 -> +0.660 (101.1% -> 102.3%) |
| OpenCode gemini-4-carbon hard (0-29) | 30 | 29/30 | 3 ([5, 18, 23]) | +0.322 -> +0.343 (64.6% -> 68.7%) | +0.360 -> +0.391 (72.0% -> 78.3%) |
| OpenCode gpt-5.5 hard (0-29) | 30 | 28/30 | 1 ([5]) | +0.504 -> +0.490 (100.9% -> 98.2%) | +0.418 -> +0.420 (83.7% -> 84.1%) |
| in-process gemini-4-carbon medium (0-29) | 30 | 26/30 | 3 ([2, 11, 18]) | +0.530 -> +0.520 (82.2% -> 80.6%) | +0.479 -> +0.498 (74.3% -> 77.2%) |
| in-process gemini-4-carbon hard (0-29) | 30 | 29/30 | 3 ([5, 6, 22]) | +0.473 -> +0.486 (94.8% -> 97.5%) | +0.421 -> +0.429 (84.3% -> 85.8%) |
| FR8 OpenCode gemini-3.5-flash medium (0-29) | 30 | 30/30 | 6 ([8, 11, 13, 22, 26, 29]) | +0.434 -> +0.580 (67.3% -> 89.9%) | +0.485 -> +0.580 (75.2% -> 89.9%) |
| OpenCode gemini-4-carbon hard 30-59 dedup union (n=6) | 6 | 6/6 | 0 ([]) | +0.658 -> +0.658 (196.5% -> 196.5%) | +0.599 -> +0.599 (129.0% -> 129.0%) |
| reference solver medium (0-29) | 30 | 27/30 | 0 ([]) | +0.645 -> +0.645 (100.0% -> 100.0%) | +0.645 -> +0.645 (100.0% -> 100.0%) |
| reference solver hard (0-29) | 30 | 30/30 | 0 ([]) | +0.499 -> +0.499 (100.0% -> 100.0%) | +0.499 -> +0.499 (100.0% -> 100.0%) |

## (b) Static Posterior Threshold Sweep (`tau in [0.60, 0.70, 0.80, 0.85, 0.90, 0.95]`)

Cells report `kept_k: luck_mean (luck_ratio)` when replacing accusations with `P(accused) < tau` by `0.0` abstention:

| Cohort | tau=0.60 | tau=0.70 | tau=0.80 | tau=0.85 | tau=0.90 | tau=0.95 |
|---|---|---|---|---|---|---|
| OpenCode gemini-4-carbon medium (0-29) | k=29: +0.658 (102.0%) | k=27: +0.653 (101.2%) | k=27: +0.653 (101.2%) | k=27: +0.653 (101.2%) | k=27: +0.653 (101.2%) | k=27: +0.653 (101.2%) |
| OpenCode gemini-4-carbon hard (0-29) | k=27: +0.388 (77.7%) | k=26: +0.391 (78.3%) | k=22: +0.358 (71.7%) | k=19: +0.329 (66.0%) | k=19: +0.329 (66.0%) | k=16: +0.284 (57.0%) |
| OpenCode gpt-5.5 hard (0-29) | k=28: +0.418 (83.7%) | k=27: +0.420 (84.1%) | k=25: +0.410 (82.0%) | k=25: +0.410 (82.0%) | k=23: +0.381 (76.2%) | k=20: +0.344 (68.9%) |
| in-process gemini-4-carbon medium (0-29) | k=23: +0.498 (77.2%) | k=22: +0.492 (76.2%) | k=22: +0.492 (76.2%) | k=22: +0.492 (76.2%) | k=22: +0.492 (76.2%) | k=22: +0.492 (76.2%) |
| in-process gemini-4-carbon hard (0-29) | k=28: +0.426 (85.4%) | k=27: +0.428 (85.8%) | k=27: +0.428 (85.8%) | k=25: +0.405 (81.1%) | k=23: +0.389 (78.0%) | k=18: +0.336 (67.3%) |
| FR8 OpenCode gemini-3.5-flash medium (0-29) | k=24: +0.580 (89.9%) | k=24: +0.580 (89.9%) | k=24: +0.580 (89.9%) | k=24: +0.580 (89.9%) | k=24: +0.580 (89.9%) | k=24: +0.580 (89.9%) |
| OpenCode gemini-4-carbon hard 30-59 dedup union (n=6) | k=6: +0.599 (129.0%) | k=6: +0.599 (129.0%) | k=6: +0.599 (129.0%) | k=6: +0.599 (129.0%) | k=6: +0.599 (129.0%) | k=5: +0.533 (114.7%) |
| reference solver medium (0-29) | k=27: +0.645 (100.0%) | k=27: +0.645 (100.0%) | k=27: +0.645 (100.0%) | k=27: +0.645 (100.0%) | k=27: +0.645 (100.0%) | k=27: +0.645 (100.0%) |
| reference solver hard (0-29) | k=30: +0.499 (100.0%) | k=30: +0.499 (100.0%) | k=30: +0.499 (100.0%) | k=30: +0.499 (100.0%) | k=27: +0.460 (92.1%) | k=24: +0.417 (83.5%) |

## (c) Two-Term Gap Decomposition (`Solver - Frontier = Stopping Loss + Evidence Deficit`)

| Cohort | Luck Gap | Luck Stopping Loss (share) | Luck Evidence Deficit (share) | Raw Gap | Raw Stopping Loss | Raw Evidence Deficit |
|---|---:|---|---|---:|---:|---:|
| OpenCode gemini-4-carbon medium (0-29) | -0.007 | +0.008 (n/a) | -0.015 (n/a) | -0.068 | -0.032 | -0.036 |
| OpenCode gemini-4-carbon hard (0-29) | +0.140 | +0.031 (22.3%) | +0.109 (77.7%) | +0.177 | +0.020 | +0.156 |
| OpenCode gpt-5.5 hard (0-29) | +0.082 | +0.002 (2.6%) | +0.079 (97.4%) | -0.005 | -0.014 | +0.009 |
| in-process gemini-4-carbon medium (0-29) | +0.166 | +0.019 (11.4%) | +0.147 (88.6%) | +0.115 | -0.011 | +0.125 |
| in-process gemini-4-carbon hard (0-29) | +0.078 | +0.008 (9.6%) | +0.071 (90.4%) | +0.026 | +0.013 | +0.013 |
| FR8 OpenCode gemini-3.5-flash medium (0-29) | +0.160 | +0.095 (59.4%) | +0.065 (40.6%) | +0.211 | +0.146 | +0.065 |
| OpenCode gemini-4-carbon hard 30-59 dedup union (n=6) | -0.135 | +0.000 (n/a) | -0.135 (n/a) | -0.323 | +0.000 | -0.323 |
| reference solver medium (0-29) | +0.000 | +0.000 (n/a) | +0.000 (n/a) | +0.000 | +0.000 | +0.000 |
| reference solver hard (0-29) | +0.000 | +0.000 (n/a) | +0.000 (n/a) | +0.000 | +0.000 | +0.000 |

## Reproduce

```bash
PYTHONPATH=. python scripts/frontier_stopping_counterfactual_v14.py --write
PYTHONPATH=. python scripts/frontier_stopping_counterfactual_v14.py --check
pytest -q tests/test_frontier_stopping_counterfactual_v14.py
```
