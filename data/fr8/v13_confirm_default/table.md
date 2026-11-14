# v1.3 confirm: CURRENT DEFAULT (e66da9f)

Overrides: none; solver behaviour_weight: code default.

Fresh dev seeds 5000-5799 (n=800 per tier x agent), v0.3 scoring (wrong accusation = -1), code e66da9f (last canary/ change 417f712). Solver = default params from code.

## easy

| agent | n | mean ± 95% CI | accuracy | wrong | none | mean accusation day |
|---|---|---|---|---|---|---|
| solver | 800 | 0.779 ± 0.009 | 0.996 | 0.001 | 0.003 | 4.99 |
| heuristic | 800 | 0.648 ± 0.019 | 0.979 | 0.021 | 0.000 | 6.86 |
| logs_only | 800 | -0.552 ± 0.050 | 0.278 | 0.723 | 0.000 | 10 |
| stop_early | 800 | -0.830 ± 0.039 | 0.085 | 0.915 | 0.000 | 1 |
| random | 800 | -0.617 ± 0.039 | 0.068 | 0.662 | 0.270 | 6.02 |
| do_nothing | 800 | 0.000 ± 0.000 | 0.000 | 0.000 | 1.000 |  |
| restrict_all | 800 | -0.741 ± 0.037 | 0.194 | 0.806 | 0.000 | 6 |
| grok_tactics | 800 | 0.690 ± 0.013 | 0.975 | 0.000 | 0.025 | 6.02 |

**Solver − heuristic (paired):** 0.131 ± 0.020; seeds needed for CI < gap/3: 165

**Solver − grok_tactics (paired):** 0.089 ± 0.016; seeds needed for CI < gap/3: 226

## medium

| agent | n | mean ± 95% CI | accuracy | wrong | none | mean accusation day |
|---|---|---|---|---|---|---|
| solver | 800 | 0.632 ± 0.017 | 0.887 | 0.000 | 0.113 | 8.09 |
| heuristic | 800 | -0.007 ± 0.054 | 0.618 | 0.383 | 0.000 | 11.17 |
| logs_only | 800 | -0.976 ± 0.014 | 0.014 | 0.986 | 0.000 | 10 |
| stop_early | 800 | -0.902 ± 0.030 | 0.049 | 0.951 | 0.000 | 1 |
| random | 800 | -0.659 ± 0.036 | 0.037 | 0.688 | 0.275 | 5.99 |
| do_nothing | 800 | 0.000 ± 0.000 | 0.000 | 0.000 | 1.000 |  |
| restrict_all | 800 | -0.948 ± 0.015 | 0.052 | 0.948 | 0.000 | 7 |
| grok_tactics | 800 | 0.459 ± 0.021 | 0.762 | 0.005 | 0.233 | 8.73 |

**Solver − heuristic (paired):** 0.639 ± 0.057; seeds needed for CI < gap/3: 57

**Solver − grok_tactics (paired):** 0.174 ± 0.025; seeds needed for CI < gap/3: 154

## hard

| agent | n | mean ± 95% CI | accuracy | wrong | none | mean accusation day |
|---|---|---|---|---|---|---|
| solver | 800 | 0.575 ± 0.028 | 0.848 | 0.039 | 0.114 | 9.42 |
| heuristic | 800 | -0.257 ± 0.058 | 0.445 | 0.555 | 0.000 | 11.61 |
| logs_only | 800 | -0.971 ± 0.016 | 0.016 | 0.984 | 0.000 | 10 |
| stop_early | 800 | -0.917 ± 0.028 | 0.041 | 0.959 | 0.000 | 1 |
| random | 800 | -0.681 ± 0.035 | 0.028 | 0.701 | 0.271 | 6.1 |
| do_nothing | 800 | 0.000 ± 0.000 | 0.000 | 0.000 | 1.000 |  |
| restrict_all | 800 | -0.985 ± 0.008 | 0.015 | 0.985 | 0.000 | 8 |
| grok_tactics | 800 | 0.342 ± 0.031 | 0.601 | 0.048 | 0.351 | 9.54 |

**Solver − heuristic (paired):** 0.832 ± 0.063; seeds needed for CI < gap/3: 42

**Solver − grok_tactics (paired):** 0.233 ± 0.040; seeds needed for CI < gap/3: 212

