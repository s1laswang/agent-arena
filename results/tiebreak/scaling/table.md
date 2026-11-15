# Tiebreak Experience Sample-Efficiency Scaling Law & Calibration Taxonomy

- Rules version: `v1.4` (`easy`, `medium`, `hard`)
- Training seeds: strictly from `TRAIN_SEEDS` (`107000..108999`), asserted disjoint from held-out and judge seeds
- Held-out evaluation: paired `HELDOUT_SEEDS` `800000..800029` (`n=30/tier` = `90` episodes/budget, secret sha256 prefix `ebf2f09716cf`)
- Policy: pure-NumPy linear/logistic-softmax investigator (`82` parameters, zero solver/world imports at inference, 100% replay-verified)

## Part A: Experience Sample-Efficiency Curve (All Tiers Pooled, n=90/budget)

| N_train | n_eval | score +/- 95% CI | luck-adj EV | accuracy | wrong-acc rate | cal-abstain rate | ECE @ commit | Brier @ commit | % of solver | replay ok |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 90 | +0.000 +/- 0.000 | +0.000 | 0.000 | 0.000 | 1.000 | n/a | n/a | 0.0% | 90/90 |
| 15 | 90 | +0.329 +/- 0.062 | +0.329 | 0.578 | 0.000 | 0.289 | 0.205 | 0.044 | 48.2% | 90/90 |
| 60 | 90 | +0.598 +/- 0.055 | +0.574 | 0.956 | 0.011 | 0.033 | 0.079 | 0.017 | 87.7% | 90/90 |
| 240 | 90 | +0.595 +/- 0.058 | +0.585 | 0.933 | 0.011 | 0.056 | 0.031 | 0.016 | 87.3% | 90/90 |
| 900 | 90 | +0.611 +/- 0.069 | +0.616 | 0.922 | 0.022 | 0.056 | 0.030 | 0.020 | 89.6% | 90/90 |
| solver (ref) | 90 | +0.682 +/- 0.053 | +0.673 | 0.956 | 0.011 | 0.033 | 0.009 | 0.012 | 100.0% | 90/90 |

## Part A Per-Tier Breakdown (n=30/tier per budget)

| N_train | easy score +/- CI | medium score +/- CI | hard score +/- CI | easy acc | medium acc | hard acc | hard luck-adj EV |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | +0.000 +/- 0.000 | +0.000 +/- 0.000 | +0.000 +/- 0.000 | 0.00 | 0.00 | 0.00 | +0.000 |
| 15 | +0.581 +/- 0.051 | +0.405 +/- 0.095 | +0.000 +/- 0.000 | 1.00 | 0.73 | 0.00 | +0.000 |
| 60 | +0.772 +/- 0.027 | +0.590 +/- 0.122 | +0.430 +/- 0.069 | 1.00 | 0.93 | 0.93 | +0.397 |
| 240 | +0.791 +/- 0.021 | +0.582 +/- 0.093 | +0.412 +/- 0.111 | 1.00 | 0.87 | 0.93 | +0.398 |
| 900 | +0.813 +/- 0.017 | +0.557 +/- 0.143 | +0.462 +/- 0.119 | 1.00 | 0.83 | 0.93 | +0.477 |
| solver (ref) | +0.793 +/- 0.041 | +0.662 +/- 0.089 | +0.590 +/- 0.118 | 1.00 | 0.90 | 0.97 | +0.572 |

## Part B: Scaling Checkpoints Episode Outcome & Calibration Taxonomy (Counts out of 90)

| N_train | cal_win | lucky_win | unlucky_noise_loss | premature_gamble | horizon_gamble | cal_abstain | missed_commit | cap_stall |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0 | 0 | 0 | 0 | 0 | 90 | 0 | 0 |
| 15 | 52 | 0 | 0 | 0 | 0 | 26 | 12 | 0 |
| 60 | 84 | 2 | 0 | 0 | 1 | 3 | 0 | 0 |
| 240 | 84 | 0 | 0 | 1 | 0 | 5 | 0 | 0 |
| 900 | 83 | 0 | 1 | 0 | 1 | 5 | 0 | 0 |
| solver (ref) | 86 | 0 | 1 | 0 | 0 | 3 | 0 | 0 |

## Part B: Cross-Model Committed v1.4 Failure-Mode & Calibration Classification

| agent | tier | n | score +/- CI | luck-adj EV | cal_win | lucky_win | unlucky_noise | premature_gamble | horizon_gamble | cal_abstain | missed_commit | cap_stall |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| opencode-gemini-4-carbon | hard | 30 | +0.322 +/- 0.199 | +0.360 | 23 | 2 | 2 | 2 | 0 | 1 | 0 | 0 |
| opencode-gemini-4-carbon | medium | 30 | +0.713 +/- 0.042 | +0.652 | 28 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| inproc-gemini-4-carbon | hard | 30 | +0.473 +/- 0.118 | +0.421 | 26 | 2 | 0 | 1 | 0 | 1 | 0 | 0 |
| inproc-gemini-4-carbon | medium | 30 | +0.530 +/- 0.138 | +0.479 | 23 | 2 | 0 | 0 | 1 | 4 | 0 | 0 |
| solver | hard | 30 | +0.499 +/- 0.119 | +0.499 | 29 | 0 | 1 | 0 | 0 | 0 | 0 | 0 |
| solver | medium | 30 | +0.645 +/- 0.087 | +0.645 | 27 | 0 | 0 | 0 | 0 | 3 | 0 | 0 |
| heuristic | hard | 20 | +0.186 +/- 0.233 | +0.095 | 16 | 1 | 1 | 2 | 0 | 0 | 0 | 0 |
| heuristic | medium | 20 | -0.275 +/- 0.361 | -0.018 | 7 | 2 | 0 | 11 | 0 | 0 | 0 | 0 |
