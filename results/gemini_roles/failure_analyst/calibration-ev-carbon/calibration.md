# Bayesian Accusation Calibration and Premature-Commit EV Report

Generated `2026-11-14T13:42:35+0000` at git `fdf16a71b039` from `data/runs/committed`.

## Headline Summary

- Episodes analyzed: 101 (100 accused, 1 abstained; accuse rate 0.990)
- Mean posterior P(accused == mole) at accusation: 0.840; empirical accuracy when accusing: 0.910
- Calibration metrics: Brier score 0.0708, ECE (10 bins) 0.0807
- Mean V_true at decision: 0.672; mean rational EV break-even threshold 1 / (1 + V_true): 0.601
- Premature commits (P(accused) < 1 / (1 + V_true)): 20 (0.198 of episodes, 0.200 of accusations)
- Expected value lost from accusing below break-even vs abstaining (score 0): 7.489 total (0.0742 per episode, 0.374 per premature commit)
- Mean realized score: 0.521; counterfactual abstain-gated score: 0.512 (delta -0.009)
- Mean Bayesian EV: 0.410; counterfactual abstain-gated Bayesian EV: 0.484

## Calibration by Agent and Tier

| version | family | agent | thinking | tier | n | accused | acc | score | gated score | mean V_true | mean 1/(1+V) | mean P(accused) | premature | EV lost total | EV lost / ep | Brier |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v1.2 | frontier | codex:gpt-5.5 | - | hard | 5 | 5 | 0.60 | -0.020 | 0.053 | 0.673 | 0.598 | 0.705 | 2 | 0.732 | 0.146 | 0.216 |
| v1.2 | frontier | codex:gpt-5.5 | - | medium | 5 | 5 | 1.00 | 0.714 | 0.714 | 0.714 | 0.586 | 1.000 | 0 | 0.000 | 0.000 | 0.000 |
| v1.2 | frontier | grok | - | hard | 5 | 4 | 0.80 | 0.567 | 0.567 | 0.652 | 0.610 | 0.995 | 0 | 0.000 | 0.000 | 0.000 |
| v1.2 | frontier | grok | - | medium | 5 | 5 | 1.00 | 0.672 | 0.672 | 0.672 | 0.601 | 0.946 | 0 | 0.000 | 0.000 | 0.011 |
| v1.2 | frontier | openai:gpt-5.5 | - | hard | 20 | 20 | 0.90 | 0.500 | 0.431 | 0.665 | 0.601 | 0.784 | 5 | 2.121 | 0.106 | 0.098 |
| v1.2 | frontier | openai:gpt-5.5 | - | medium | 20 | 20 | 0.95 | 0.600 | 0.649 | 0.677 | 0.600 | 0.937 | 1 | 0.795 | 0.040 | 0.008 |
| v1.2 | frontier | opencode:openai/gpt-5.6-sol | - | hard | 1 | 1 | 1.00 | 0.635 | 0.635 | 0.635 | 0.612 | 0.691 | 0 | 0.000 | 0.000 | 0.095 |
| v1.2 | frontier | opencode:openai/gpt-5.6-sol | - | medium | 1 | 1 | 1.00 | 0.620 | 0.000 | 0.620 | 0.617 | 0.552 | 1 | 0.106 | 0.106 | 0.201 |
| v1.3 | frontier | codex:gpt-5.5 | - | hard | 11 | 11 | 1.00 | 0.655 | 0.515 | 0.655 | 0.605 | 0.818 | 2 | 0.487 | 0.044 | 0.083 |
| v1.3 | frontier | codex:gpt-5.5 | - | medium | 11 | 11 | 0.82 | 0.401 | 0.430 | 0.705 | 0.591 | 0.719 | 5 | 1.994 | 0.181 | 0.092 |
| v1.3 | frontier | openai:gpt-5.5 | - | hard | 8 | 8 | 0.75 | 0.264 | 0.434 | 0.659 | 0.603 | 0.747 | 3 | 1.017 | 0.127 | 0.163 |
| v1.3 | frontier | openai:gpt-5.5 | - | medium | 9 | 9 | 1.00 | 0.668 | 0.617 | 0.668 | 0.604 | 0.917 | 1 | 0.238 | 0.026 | 0.033 |

## Reliability Bins

| bin | count | mean P(accused) | empirical acc | abs gap | mean 1/(1+V) | mean score | mean EV | premature | EV lost |
|---|---|---|---|---|---|---|---|---|---|
| [0.00, 0.10) | 0 | NA | NA | NA | NA | NA | NA | 0 | 0.000 |
| [0.10, 0.20) | 6 | 0.152 | 0.333 | 0.181 | 0.605 | -0.472 | -0.745 | 6 | 4.467 |
| [0.20, 0.30) | 0 | NA | NA | NA | NA | NA | NA | 0 | 0.000 |
| [0.30, 0.40) | 1 | 0.330 | 0.000 | 0.330 | 0.658 | -1.000 | -0.498 | 1 | 0.498 |
| [0.40, 0.50) | 6 | 0.445 | 0.833 | 0.388 | 0.607 | +0.391 | -0.266 | 6 | 1.593 |
| [0.50, 0.60) | 7 | 0.549 | 0.857 | 0.308 | 0.636 | +0.348 | -0.133 | 7 | 0.931 |
| [0.60, 0.70) | 5 | 0.647 | 0.800 | 0.153 | 0.603 | +0.324 | +0.072 | 0 | 0.000 |
| [0.70, 0.80) | 2 | 0.753 | 1.000 | 0.247 | 0.635 | +0.575 | +0.185 | 0 | 0.000 |
| [0.80, 0.90) | 5 | 0.862 | 1.000 | 0.138 | 0.600 | +0.669 | +0.438 | 0 | 0.000 |
| [0.90, 1.00] | 68 | 0.989 | 0.985 | 0.003 | 0.592 | +0.670 | +0.676 | 0 | 0.000 |

## Worst Premature Accusations (Below 1 / (1 + V_true))

| version | agent | tier | seed | day | accused | correct | score | V_true | 1/(1+V) | P(accused) | P(top) | EV(accuse) | EV lost | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v1.2 | openai:gpt-5.5 | hard | 15 | 14 | e08 | False | -1.00 | 0.635 | 0.612 | 0.113 | 0.535 | -0.815 | 0.815 | premature_wrong |
| v1.2 | openai:gpt-5.5 | hard | 8 | 14 | e13 | True | +0.53 | 0.530 | 0.654 | 0.130 | 0.489 | -0.801 | 0.801 | premature_lucky |
| v1.2 | openai:gpt-5.5 | medium | 17 | 14 | e19 | False | -1.00 | 0.560 | 0.641 | 0.132 | 0.192 | -0.795 | 0.795 | premature_wrong |
| v1.3 | openai:gpt-5.5 | hard | 2 | 13 | e19 | True | +0.64 | 0.635 | 0.612 | 0.169 | 0.576 | -0.723 | 0.723 | premature_lucky |
| v1.2 | codex:gpt-5.5 | hard | 1 | 14 | e06 | False | -1.00 | 0.775 | 0.563 | 0.186 | 0.293 | -0.669 | 0.669 | premature_wrong |
| v1.3 | codex:gpt-5.5 | medium | 0 | 6 | e02 | False | -1.00 | 0.830 | 0.546 | 0.183 | 0.183 | -0.664 | 0.664 | premature_wrong |
| v1.3 | codex:gpt-5.5 | medium | 4 | 14 | e07 | False | -1.00 | 0.520 | 0.658 | 0.330 | 0.330 | -0.498 | 0.498 | premature_wrong |
| v1.3 | codex:gpt-5.5 | medium | 5 | 14 | e14 | True | +0.59 | 0.590 | 0.629 | 0.410 | 0.410 | -0.348 | 0.348 | premature_lucky |
| v1.2 | openai:gpt-5.5 | hard | 16 | 14 | e20 | True | +0.57 | 0.575 | 0.635 | 0.445 | 0.465 | -0.299 | 0.299 | premature_lucky |
| v1.3 | codex:gpt-5.5 | hard | 8 | 11 | e13 | True | +0.76 | 0.760 | 0.568 | 0.408 | 0.408 | -0.281 | 0.281 | premature_lucky |
| v1.3 | codex:gpt-5.5 | medium | 3 | 14 | e14 | True | +0.44 | 0.440 | 0.694 | 0.525 | 0.525 | -0.244 | 0.244 | premature_lucky |
| v1.3 | codex:gpt-5.5 | medium | 7 | 9 | e09 | True | +0.65 | 0.650 | 0.606 | 0.461 | 0.461 | -0.240 | 0.240 | premature_lucky |
| v1.3 | openai:gpt-5.5 | medium | 4 | 14 | e17 | True | +0.46 | 0.460 | 0.685 | 0.522 | 0.522 | -0.238 | 0.238 | premature_lucky |
| v1.3 | openai:gpt-5.5 | hard | 4 | 14 | e26 | False | -1.00 | 0.565 | 0.639 | 0.498 | 0.498 | -0.220 | 0.220 | premature_wrong |
| v1.3 | codex:gpt-5.5 | hard | 3 | 12 | e26 | True | +0.77 | 0.770 | 0.565 | 0.449 | 0.449 | -0.206 | 0.206 | premature_lucky |

## Reference Baselines (Context Only)

| version | agent | tier | n | accused | acc | score | mean 1/(1+V) | mean P(accused) | premature | EV lost total |
|---|---|---|---|---|---|---|---|---|---|---|
| v1.2 | do_nothing | hard | 20 | 0 | 0.00 | 0.000 | 0.580 | NA | 0 | 0.000 |
| v1.2 | do_nothing | medium | 20 | 0 | 0.00 | 0.000 | 0.631 | NA | 0 | 0.000 |
| v1.2 | heuristic | hard | 20 | 20 | 0.40 | -0.322 | 0.605 | 0.401 | 17 | 8.126 |
| v1.2 | heuristic | medium | 20 | 20 | 0.55 | -0.115 | 0.634 | 0.605 | 13 | 5.100 |
| v1.2 | random | hard | 20 | 14 | 0.00 | -0.700 | 0.624 | 0.014 | 14 | 13.614 |
| v1.2 | random | medium | 20 | 15 | 0.05 | -0.678 | 0.637 | 0.083 | 15 | 13.012 |
| v1.2 | restrict_all | hard | 20 | 20 | 0.00 | -1.000 | 1.000 | 0.018 | 20 | 19.646 |
| v1.2 | restrict_all | medium | 20 | 20 | 0.05 | -0.950 | 1.000 | 0.052 | 20 | 18.965 |
| v1.2 | solver | hard | 20 | 18 | 0.85 | 0.584 | 0.585 | 0.947 | 0 | 0.000 |
| v1.2 | solver | medium | 20 | 19 | 0.95 | 0.690 | 0.586 | 1.000 | 0 | 0.000 |
| v1.2 | stop_early | hard | 20 | 20 | 0.05 | -0.900 | 0.500 | 0.033 | 20 | 18.667 |
| v1.2 | stop_early | medium | 20 | 20 | 0.00 | -1.000 | 0.500 | 0.050 | 20 | 18.000 |
| v1.3 | do_nothing | hard | 20 | 0 | 0.00 | 0.000 | 0.580 | NA | 0 | 0.000 |
| v1.3 | do_nothing | medium | 20 | 0 | 0.00 | 0.000 | 0.631 | NA | 0 | 0.000 |
| v1.3 | heuristic | hard | 20 | 20 | 0.40 | -0.322 | 0.605 | 0.401 | 17 | 8.126 |
| v1.3 | heuristic | medium | 20 | 20 | 0.55 | -0.115 | 0.634 | 0.605 | 13 | 5.100 |
| v1.3 | random | hard | 20 | 14 | 0.00 | -0.700 | 0.624 | 0.014 | 14 | 13.614 |
| v1.3 | random | medium | 20 | 15 | 0.05 | -0.678 | 0.637 | 0.083 | 15 | 13.012 |
| v1.3 | restrict_all | hard | 20 | 20 | 0.00 | -1.000 | 1.000 | 0.018 | 20 | 19.646 |
| v1.3 | restrict_all | medium | 20 | 20 | 0.05 | -0.950 | 1.000 | 0.052 | 20 | 18.965 |
| v1.3 | solver | hard | 20 | 17 | 0.85 | 0.592 | 0.594 | 0.914 | 0 | 0.000 |
| v1.3 | solver | medium | 20 | 20 | 1.00 | 0.717 | 0.585 | 1.000 | 0 | 0.000 |
| v1.3 | stop_early | hard | 20 | 20 | 0.05 | -0.900 | 0.500 | 0.033 | 20 | 18.667 |
| v1.3 | stop_early | medium | 20 | 20 | 0.00 | -1.000 | 0.500 | 0.050 | 20 | 18.000 |
| v1.4 | do_nothing | hard | 20 | 0 | 0.00 | 0.000 | 0.759 | NA | 0 | 0.000 |
| v1.4 | do_nothing | medium | 20 | 0 | 0.00 | 0.000 | 0.631 | NA | 0 | 0.000 |
| v1.4 | heuristic | hard | 20 | 20 | 0.85 | 0.186 | 0.746 | 0.787 | 3 | 2.410 |
| v1.4 | heuristic | medium | 20 | 20 | 0.45 | -0.275 | 0.635 | 0.617 | 13 | 4.655 |
| v1.4 | random | hard | 20 | 17 | 0.00 | -0.850 | 0.704 | 0.017 | 17 | 16.476 |
| v1.4 | random | medium | 20 | 15 | 0.05 | -0.678 | 0.637 | 0.083 | 15 | 13.012 |
| v1.4 | restrict_all | hard | 20 | 20 | 0.00 | -1.000 | 1.000 | 0.007 | 20 | 19.866 |
| v1.4 | restrict_all | medium | 20 | 20 | 0.05 | -0.950 | 1.000 | 0.052 | 20 | 18.965 |
| v1.4 | solver | hard | 20 | 20 | 0.95 | 0.464 | 0.656 | 0.966 | 0 | 0.000 |
| v1.4 | solver | medium | 20 | 20 | 1.00 | 0.717 | 0.585 | 1.000 | 0 | 0.000 |
| v1.4 | stop_early | hard | 20 | 20 | 0.00 | -1.000 | 0.500 | 0.025 | 20 | 19.000 |
| v1.4 | stop_early | medium | 20 | 20 | 0.00 | -1.000 | 0.500 | 0.050 | 20 | 18.000 |

Figure: `calibration_curve.png`. Data: `calibration.json`.
