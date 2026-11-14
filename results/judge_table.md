# Canary judge table

- seeds: 40 judge seeds per tier (900000..900039)
- judge-world secret: statistical, sha256 fingerprint `2759407705e1` (statistical reproduction; set CANARY_WORLD_SECRET for exact numbers)
- git: `505948daa188`, generated 2026-11-14T11:24:11+0200, 1.6 s
- reward: true V at accusation if correct (V starts at 1.0 and drops with every leak, including leaks that have not surfaced yet; v1.3 `status` shows only surfaced damage), -1 if wrong, 0 if no accusation
- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation
- `/ solver` = agent mean / solver mean on the same tier (ratio of means); `pass^k` only for agents with k repeated runs per seed
- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). **reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the team's worlds, so they are NOT paired with this run; compare them by mean ± CI only
- reported runs are grouped by tier version and never pooled: v1.3 (current rules) first, then earlier versions as history (not comparable to the paired table; `/ solver` left blank). Builds under data/runs/committed/superseded/ are excluded
- per-episode timeout guard: 60 s; no episode timed out

## medium (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.643 ± 0.076 | 0.90 | 36/40 | 8.2 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.120 ± 0.231 | 0.70 | 40/40 | 11.2 | 0.19 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.955 ± 0.088 | 0.03 | 40/40 | 10.0 | -1.48 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.725 ± 0.140 | 0.00 | 29/40 | 4.5 | -1.13 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.850 ± 0.165 | 0.07 | 40/40 | 1.0 | -1.32 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs: v1.3 (current rules):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 11 | +0.401 ± 0.417 | 0.82 | 11/11 | 8.8 | 0.62 | – | replayed, NON-judge seeds, 11 seeds, git 1724a48 (data/runs/committed/v1.3/codex-gpt-5.5-full/medium) |
| openai:gpt-5.5 | reported | 9 | +0.668 ± 0.103 | 1.00 | 9/9 | 9.9 | 1.04 | – | replayed, NON-judge seeds, 9 seeds, git 1724a48 (data/runs/committed/v1.3/gpt-5.5-full/medium) |
| restrict_all | reported | 20 | -0.950 ± 0.098 | 0.05 | 20/20 | 7.0 | -1.48 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/restrict_all-medium-20261114-0332) |
| solver | reported | 20 | +0.717 ± 0.052 | 1.00 | 20/20 | 7.5 | 1.11 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/solver-medium-20261114-0332) |
| heuristic | reported | 20 | -0.116 ± 0.361 | 0.55 | 20/20 | 11.1 | -0.18 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/heuristic-medium-20261114-0332) |
| random | reported | 20 | -0.678 ± 0.225 | 0.05 | 15/20 | 6.5 | -1.05 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/random-medium-20261114-0332) |
| stop_early | reported | 20 | -1.000 ± 0.000 | 0.00 | 20/20 | 1.0 | -1.55 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/stop_early-medium-20261114-0332) |
| do_nothing | reported | 20 | +0.000 ± 0.000 | 0.00 | 0/20 | – | 0.00 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/do_nothing-medium-20261114-0332) |

History: v1.2 (earlier rules, not comparable to the paired table):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 5 | +0.714 ± 0.106 | 1.00 | 5/5 | 7.4 | – | – | replayed, NON-judge seeds, 5 seeds, git 868e5de (data/runs/committed/codex-gpt-5.5/medium) |
| grok | reported | 5 | +0.672 ± 0.109 | 1.00 | 5/5 | 9.0 | – | – | replayed, judge seeds, 5 seeds, git unknown (data/runs/committed/grok/medium) |
| openai:gpt-5.5 | reported | 20 | +0.600 ± 0.175 | 0.95 | 20/20 | 8.8 | – | – | replayed, NON-judge seeds, 20 seeds, git 6e2455f, db104c9, e02b831 (data/runs/committed/gpt-5.5/medium-0-4, data/runs/committed/gpt-5.5/medium-10-14, data/runs/committed/gpt-5.5/medium-15-19, data/runs/committed/gpt-5.5/medium-5-9) |
| opencode:openai/gpt-5.6-sol | reported | 5 | +0.124 ± 0.243 | 0.20 | 1/5 | 11.0 | – | – | replayed, NON-judge seeds, 5 seeds, git 43b28b0 (data/runs/committed/opencode-gpt-5.6-sol/medium) |
| restrict_all | reported | 20 | -0.950 ± 0.098 | 0.05 | 20/20 | 7.0 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/restrict_all-medium-20261114-0253) |
| solver | reported | 20 | +0.690 ± 0.086 | 0.95 | 19/20 | 7.4 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/solver-medium-20261114-0253) |
| heuristic | reported | 20 | -0.116 ± 0.361 | 0.55 | 20/20 | 11.1 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/heuristic-medium-20261114-0253) |
| random | reported | 20 | -0.678 ± 0.225 | 0.05 | 15/20 | 6.5 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/random-medium-20261114-0253) |
| stop_early | reported | 20 | -1.000 ± 0.000 | 0.00 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/stop_early-medium-20261114-0253) |
| do_nothing | reported | 20 | +0.000 ± 0.000 | 0.00 | 0/20 | – | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/do_nothing-medium-20261114-0253) |

## hard (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.605 ± 0.114 | 0.85 | 35/40 | 8.9 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.465 ± 0.242 | 0.33 | 40/40 | 11.5 | -0.77 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.65 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.764 ± 0.155 | 0.05 | 34/40 | 6.4 | -1.26 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.950 ± 0.098 | 0.03 | 40/40 | 1.0 | -1.57 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs: v1.3 (current rules):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 11 | +0.655 ± 0.041 | 1.00 | 11/11 | 11.6 | 1.08 | – | replayed, NON-judge seeds, 11 seeds, git 1724a48 (data/runs/committed/v1.3/codex-gpt-5.5-full/hard) |
| openai:gpt-5.5 | reported | 8 | +0.264 ± 0.541 | 0.75 | 8/8 | 12.2 | 0.44 | – | replayed, NON-judge seeds, 8 seeds, git 1724a48 (data/runs/committed/v1.3/gpt-5.5-full/hard) |
| restrict_all | reported | 20 | -1.000 ± 0.000 | 0.00 | 20/20 | 8.0 | -1.65 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/restrict_all-hard-20261114-0332) |
| solver | reported | 20 | +0.592 ± 0.114 | 0.85 | 17/20 | 10.8 | 0.98 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/solver-hard-20261114-0332) |
| heuristic | reported | 20 | -0.322 ± 0.374 | 0.40 | 20/20 | 11.6 | -0.53 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/heuristic-hard-20261114-0332) |
| random | reported | 20 | -0.700 ± 0.206 | 0.00 | 14/20 | 6.6 | -1.16 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/random-hard-20261114-0332) |
| stop_early | reported | 20 | -0.900 ± 0.196 | 0.05 | 20/20 | 1.0 | -1.49 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/stop_early-hard-20261114-0332) |
| do_nothing | reported | 20 | +0.000 ± 0.000 | 0.00 | 0/20 | – | 0.00 | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/do_nothing-hard-20261114-0332) |

History: v1.2 (earlier rules, not comparable to the paired table):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 6 | +0.095 ± 0.679 | 0.67 | 6/6 | 12.7 | – | – | replayed, NON-judge seeds, 5 seeds, git 43b28b0, 868e5de (data/runs/committed/codex-gpt-5.5-smoke/hard, data/runs/committed/codex-gpt-5.5/hard) |
| grok | reported | 5 | +0.567 ± 0.286 | 0.80 | 4/5 | 9.5 | – | – | replayed, judge seeds, 5 seeds, git unknown (data/runs/committed/grok/hard) |
| openai:gpt-5.5 | reported | 20 | +0.500 ± 0.227 | 0.90 | 20/20 | 11.8 | – | – | replayed, NON-judge seeds, 20 seeds, git 6e2455f, d2b85a9 (data/runs/committed/gpt-5.5/hard-0-4, data/runs/committed/gpt-5.5/hard-10-14, data/runs/committed/gpt-5.5/hard-15-19, data/runs/committed/gpt-5.5/hard-5-9) |
| opencode:openai/gpt-5.6-sol | reported | 5 | +0.127 ± 0.249 | 0.20 | 1/5 | 14.0 | – | – | replayed, NON-judge seeds, 5 seeds, git 43b28b0 (data/runs/committed/opencode-gpt-5.6-sol/hard) |
| restrict_all | reported | 20 | -1.000 ± 0.000 | 0.00 | 20/20 | 8.0 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/restrict_all-hard-20261114-0253) |
| solver | reported | 20 | +0.584 ± 0.194 | 0.85 | 18/20 | 9.6 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/solver-hard-20261114-0253) |
| heuristic | reported | 20 | -0.322 ± 0.374 | 0.40 | 20/20 | 11.6 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/heuristic-hard-20261114-0253) |
| random | reported | 20 | -0.700 ± 0.206 | 0.00 | 14/20 | 6.6 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/random-hard-20261114-0253) |
| stop_early | reported | 20 | -0.900 ± 0.196 | 0.05 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/stop_early-hard-20261114-0253) |
| do_nothing | reported | 20 | +0.000 ± 0.000 | 0.00 | 0/20 | – | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/do_nothing-hard-20261114-0253) |

## easy (sanity tier)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.784 ± 0.037 | 1.00 | 40/40 | 5.0 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.600 ± 0.092 | 0.97 | 40/40 | 7.8 | 0.77 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.401 ± 0.243 | 0.38 | 40/40 | 10.0 | -0.51 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.674 ± 0.174 | 0.07 | 32/40 | 6.5 | -0.86 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.950 ± 0.098 | 0.03 | 40/40 | 1.0 | -1.21 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |
