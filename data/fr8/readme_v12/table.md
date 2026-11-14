# Canary confirmation table (tiers v1.2)

Overrides: none; solver behaviour_weight: code default.

Fresh dev seeds 1000-1999 (n=1000 per tier x agent), v0.3 scoring (wrong accusation = -1), code d954bad (last canary/ change c11cba6). Solver = default params from code.

## easy

| agent | n | mean ± 95% CI | accuracy | wrong | none | mean accusation day |
|---|---|---|---|---|---|---|
| solver | 1000 | 0.773 ± 0.008 | 0.995 | 0.000 | 0.005 | 5.07 |
| heuristic | 1000 | 0.648 ± 0.017 | 0.977 | 0.023 | 0.000 | 6.78 |
| logs_only | 1000 | -0.497 ± 0.046 | 0.313 | 0.687 | 0.000 | 10 |
| stop_early | 1000 | -0.846 ± 0.033 | 0.077 | 0.923 | 0.000 | 1 |
| random | 1000 | -0.591 ± 0.035 | 0.062 | 0.634 | 0.304 | 6.03 |
| do_nothing | 1000 | 0.000 ± 0.000 | 0.000 | 0.000 | 1.000 |  |
| restrict_all | 1000 | -0.729 ± 0.033 | 0.203 | 0.797 | 0.000 | 6 |

**Solver − heuristic (paired):** 0.125 ± 0.018; seeds needed for CI < gap/3: 184

## medium

| agent | n | mean ± 95% CI | accuracy | wrong | none | mean accusation day |
|---|---|---|---|---|---|---|
| solver | 1000 | 0.646 ± 0.015 | 0.908 | 0.000 | 0.092 | 8.17 |
| heuristic | 1000 | -0.040 ± 0.049 | 0.595 | 0.405 | 0.000 | 11.16 |
| logs_only | 1000 | -0.976 ± 0.013 | 0.014 | 0.986 | 0.000 | 10 |
| stop_early | 1000 | -0.904 ± 0.026 | 0.048 | 0.952 | 0.000 | 1 |
| random | 1000 | -0.639 ± 0.034 | 0.043 | 0.673 | 0.284 | 5.99 |
| do_nothing | 1000 | 0.000 ± 0.000 | 0.000 | 0.000 | 1.000 |  |
| restrict_all | 1000 | -0.947 ± 0.014 | 0.053 | 0.947 | 0.000 | 7 |

**Solver − heuristic (paired):** 0.687 ± 0.050; seeds needed for CI < gap/3: 49

## hard

| agent | n | mean ± 95% CI | accuracy | wrong | none | mean accusation day |
|---|---|---|---|---|---|---|
| solver | 1000 | 0.555 ± 0.025 | 0.824 | 0.040 | 0.136 | 9.56 |
| heuristic | 1000 | -0.286 ± 0.051 | 0.430 | 0.570 | 0.000 | 11.66 |
| logs_only | 1000 | -0.980 ± 0.012 | 0.011 | 0.989 | 0.000 | 10 |
| stop_early | 1000 | -0.916 ± 0.025 | 0.042 | 0.958 | 0.000 | 1 |
| random | 1000 | -0.641 ± 0.032 | 0.024 | 0.659 | 0.317 | 6.05 |
| do_nothing | 1000 | 0.000 ± 0.000 | 0.000 | 0.000 | 1.000 |  |
| restrict_all | 1000 | -0.987 ± 0.007 | 0.013 | 0.987 | 0.000 | 8 |

**Solver − heuristic (paired):** 0.841 ± 0.055; seeds needed for CI < gap/3: 39

