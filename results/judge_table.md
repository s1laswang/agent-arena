# Canary judge table

- seeds: 40 judge seeds per tier (900000..900039)
- judge-world secret: statistical, sha256 fingerprint `3a7d7db9b23d` (statistical reproduction; set CANARY_WORLD_SECRET for exact numbers)
- git: `59bed26bbe5b`, generated 2026-11-14T12:30:58+0200, 4.1 s
- reward: true V at accusation if correct (V starts at 1.0 and drops with every leak, including leaks that have not surfaced yet; v1.3 `status` shows only surfaced damage), -1 if wrong, 0 if no accusation
- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation
- `/ solver` = agent mean / solver mean on the same tier (ratio of means); `pass^k` only for agents with k repeated runs per seed
- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). **reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the team's worlds, so they are NOT paired with this run; compare them by mean ± CI only
- reported runs are grouped by tier version and never pooled: v1.4 (current rules) first, then earlier versions as history (not comparable to the paired table; `/ solver` left blank). Builds under data/runs/committed/superseded/ are excluded
- per-episode timeout guard: 60 s; no episode timed out

## medium (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | 0 | +0.673 ± 0.060 | 0.95 | 38/40 | 8.2 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | 0 | +0.132 ± 0.233 | 0.70 | 40/40 | 11.2 | 0.20 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | 0 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.49 | – | strongest no-canary log reader |
| random | baseline | 40 | 0 | -0.583 ± 0.191 | 0.07 | 29/40 | 4.5 | -0.87 | – | random valid tool calls |
| stop_early | baseline | 40 | 0 | -0.900 ± 0.137 | 0.05 | 40/40 | 1.0 | -1.34 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | 0 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs: v1.4 (current rules):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | – | pending | – | – | – | – | – | pending: no v1.4 runs in data/runs/committed/ yet |

History: v1.3 (earlier rules, not comparable to the paired table):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 11 | 0 | +0.401 ± 0.417 | 0.82 | 11/11 | 8.8 | – | – | replayed, NON-judge seeds, 11 seeds, git 1724a48 (data/runs/committed/v1.3/codex-gpt-5.5-full/medium) |
| openai:gpt-5.5 | reported | 9 | 0 | +0.668 ± 0.103 | 1.00 | 9/9 | 9.9 | – | – | replayed, NON-judge seeds, 9 seeds, git 1724a48 (data/runs/committed/v1.3/gpt-5.5-full/medium) |
| restrict_all | reported | 20 | 0 | -0.950 ± 0.098 | 0.05 | 20/20 | 7.0 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/restrict_all-medium-20261114-0332) |
| solver | reported | 20 | 0 | +0.717 ± 0.052 | 1.00 | 20/20 | 7.5 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/solver-medium-20261114-0332) |
| heuristic | reported | 20 | 0 | -0.116 ± 0.361 | 0.55 | 20/20 | 11.1 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/heuristic-medium-20261114-0332) |
| random | reported | 20 | 0 | -0.678 ± 0.225 | 0.05 | 15/20 | 6.5 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/random-medium-20261114-0332) |
| stop_early | reported | 20 | 0 | -1.000 ± 0.000 | 0.00 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/stop_early-medium-20261114-0332) |
| do_nothing | reported | 20 | 0 | +0.000 ± 0.000 | 0.00 | 0/20 | – | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/do_nothing-medium-20261114-0332) |

History: v1.2 (earlier rules, not comparable to the paired table):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 5 | 0 | +0.714 ± 0.106 | 1.00 | 5/5 | 7.4 | – | – | replayed, NON-judge seeds, 5 seeds, git 868e5de (data/runs/committed/codex-gpt-5.5/medium) |
| grok | reported | 5 | 0 | +0.672 ± 0.109 | 1.00 | 5/5 | 9.0 | – | – | replayed, judge seeds, 5 seeds, git unknown (data/runs/committed/grok/medium) |
| openai:gpt-5.5 | reported | 20 | 0 | +0.600 ± 0.175 | 0.95 | 20/20 | 8.8 | – | – | replayed, NON-judge seeds, 20 seeds, git 6e2455f, db104c9, e02b831 (data/runs/committed/gpt-5.5/medium-0-4, data/runs/committed/gpt-5.5/medium-10-14, data/runs/committed/gpt-5.5/medium-15-19, data/runs/committed/gpt-5.5/medium-5-9) |
| opencode:openai/gpt-5.6-sol | reported | 1 | 4 (infra:opencode_db_locked, infra:provider_quota ×2, mcp server died) | +0.620 ± 0.000 | 1.00 | 1/1 | 11.0 | – | – | replayed, NON-judge seeds, 1 seeds, git 43b28b0 (data/runs/committed/opencode-gpt-5.6-sol/medium) |
| restrict_all | reported | 20 | 0 | -0.950 ± 0.098 | 0.05 | 20/20 | 7.0 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/restrict_all-medium-20261114-0253) |
| solver | reported | 20 | 0 | +0.690 ± 0.086 | 0.95 | 19/20 | 7.4 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/solver-medium-20261114-0253) |
| heuristic | reported | 20 | 0 | -0.116 ± 0.361 | 0.55 | 20/20 | 11.1 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/heuristic-medium-20261114-0253) |
| random | reported | 20 | 0 | -0.678 ± 0.225 | 0.05 | 15/20 | 6.5 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/random-medium-20261114-0253) |
| stop_early | reported | 20 | 0 | -1.000 ± 0.000 | 0.00 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/stop_early-medium-20261114-0253) |
| do_nothing | reported | 20 | 0 | +0.000 ± 0.000 | 0.00 | 0/20 | – | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/do_nothing-medium-20261114-0253) |

## hard (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | 0 | +0.613 ± 0.040 | 1.00 | 40/40 | 8.9 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | 0 | -0.012 ± 0.183 | 0.75 | 40/40 | 15.8 | -0.02 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | 0 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.63 | – | strongest no-canary log reader |
| random | baseline | 40 | 0 | -0.783 ± 0.140 | 0.03 | 33/40 | 6.8 | -1.28 | – | random valid tool calls |
| stop_early | baseline | 40 | 0 | -1.000 ± 0.000 | 0.00 | 40/40 | 1.0 | -1.63 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | 0 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs: v1.4 (current rules):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | – | pending | – | – | – | – | – | pending: no v1.4 runs in data/runs/committed/ yet |

History: v1.3 (earlier rules, not comparable to the paired table):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 11 | 0 | +0.655 ± 0.041 | 1.00 | 11/11 | 11.6 | – | – | replayed, NON-judge seeds, 11 seeds, git 1724a48 (data/runs/committed/v1.3/codex-gpt-5.5-full/hard) |
| openai:gpt-5.5 | reported | 8 | 0 | +0.264 ± 0.541 | 0.75 | 8/8 | 12.2 | – | – | replayed, NON-judge seeds, 8 seeds, git 1724a48 (data/runs/committed/v1.3/gpt-5.5-full/hard) |
| restrict_all | reported | 20 | 0 | -1.000 ± 0.000 | 0.00 | 20/20 | 8.0 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/restrict_all-hard-20261114-0332) |
| solver | reported | 20 | 0 | +0.592 ± 0.114 | 0.85 | 17/20 | 10.8 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/solver-hard-20261114-0332) |
| heuristic | reported | 20 | 0 | -0.322 ± 0.374 | 0.40 | 20/20 | 11.6 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/heuristic-hard-20261114-0332) |
| random | reported | 20 | 0 | -0.700 ± 0.206 | 0.00 | 14/20 | 6.6 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/random-hard-20261114-0332) |
| stop_early | reported | 20 | 0 | -0.900 ± 0.196 | 0.05 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/stop_early-hard-20261114-0332) |
| do_nothing | reported | 20 | 0 | +0.000 ± 0.000 | 0.00 | 0/20 | – | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/do_nothing-hard-20261114-0332) |

History: v1.2 (earlier rules, not comparable to the paired table):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 5 | 0 | -0.020 ± 0.784 | 0.60 | 5/5 | 12.6 | – | – | replayed, NON-judge seeds, 5 seeds, git 868e5de (data/runs/committed/codex-gpt-5.5/hard) |
| grok | reported | 5 | 0 | +0.567 ± 0.286 | 0.80 | 4/5 | 9.5 | – | – | replayed, judge seeds, 5 seeds, git unknown (data/runs/committed/grok/hard) |
| openai:gpt-5.5 | reported | 20 | 0 | +0.500 ± 0.227 | 0.90 | 20/20 | 11.8 | – | – | replayed, NON-judge seeds, 20 seeds, git 6e2455f, d2b85a9 (data/runs/committed/gpt-5.5/hard-0-4, data/runs/committed/gpt-5.5/hard-10-14, data/runs/committed/gpt-5.5/hard-15-19, data/runs/committed/gpt-5.5/hard-5-9) |
| opencode:openai/gpt-5.6-sol | reported | 1 | 4 (infra:provider_quota ×3, mcp server died) | +0.635 ± 0.000 | 1.00 | 1/1 | 14.0 | – | – | replayed, NON-judge seeds, 1 seeds, git 43b28b0 (data/runs/committed/opencode-gpt-5.6-sol/hard) |
| restrict_all | reported | 20 | 0 | -1.000 ± 0.000 | 0.00 | 20/20 | 8.0 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/restrict_all-hard-20261114-0253) |
| solver | reported | 20 | 0 | +0.584 ± 0.194 | 0.85 | 18/20 | 9.6 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/solver-hard-20261114-0253) |
| heuristic | reported | 20 | 0 | -0.322 ± 0.374 | 0.40 | 20/20 | 11.6 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/heuristic-hard-20261114-0253) |
| random | reported | 20 | 0 | -0.700 ± 0.206 | 0.00 | 14/20 | 6.6 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/random-hard-20261114-0253) |
| stop_early | reported | 20 | 0 | -0.900 ± 0.196 | 0.05 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/stop_early-hard-20261114-0253) |
| do_nothing | reported | 20 | 0 | +0.000 ± 0.000 | 0.00 | 0/20 | – | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/do_nothing-hard-20261114-0253) |

## easy (sanity tier)

Paired runs (this invocation, same worlds):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | 0 | +0.778 ± 0.040 | 1.00 | 40/40 | 5.0 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | 0 | +0.628 ± 0.092 | 0.97 | 40/40 | 7.0 | 0.81 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | 0 | -0.713 ± 0.196 | 0.17 | 40/40 | 10.0 | -0.92 | – | strongest no-canary log reader |
| random | baseline | 40 | 0 | -0.621 ± 0.193 | 0.10 | 32/40 | 6.5 | -0.80 | – | random valid tool calls |
| stop_early | baseline | 40 | 0 | -0.900 ± 0.137 | 0.05 | 40/40 | 1.0 | -1.16 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | 0 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |
