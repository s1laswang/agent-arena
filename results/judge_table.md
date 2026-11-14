# Canary judge table

- seeds: 40 judge seeds per tier (900000..900039)
- judge-world secret: statistical, sha256 fingerprint `86036614b2a9` (statistical reproduction; set CANARY_WORLD_SECRET for exact numbers)
- git: `01a6ac763e41`, generated 2026-11-14T23:49:13+0200, 26.2 s
- reward: true V at accusation if correct (V starts at 1.0 and drops with every leak, including leaks that have not surfaced yet; v1.3 `status` shows only surfaced damage), -1 if wrong, 0 if no accusation
- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation
- `/ solver` = agent mean / solver mean on the same tier (ratio of means); `pass^k` only for agents with k repeated runs per seed
- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). **reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the team's worlds, so they are NOT paired with this run; compare them by mean ± CI only
- **v1.4 frontier vs solver, paired on the same seeds:** `data/runs/committed/v1.4/paired_table_gemini.md`, explained in `docs/reports/gap.md`. The v1.4 reported rows below replay those committed episodes (played on dev seeds under the team's secret), so they are not paired with this invocation's judge worlds.
- reported runs are grouped by tier version and never pooled: v1.4 (current rules) first, then earlier versions as history (not comparable to the paired table; `/ solver` left blank). Builds under data/runs/committed/superseded/ are excluded
- per-episode timeout guard: 60 s; no episode timed out

## medium (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | 0 | +0.575 ± 0.090 | 0.82 | 33/40 | 8.4 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | 0 | +0.019 ± 0.248 | 0.62 | 40/40 | 11.0 | 0.03 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | 0 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.74 | – | strongest no-canary log reader |
| random | baseline | 40 | 0 | -0.600 ± 0.180 | 0.07 | 29/40 | 4.5 | -1.04 | – | random valid tool calls |
| guess_day1 | baseline | 40 | 0 | -1.000 ± 0.000 | 0.00 | 40/40 | 1.0 | -1.74 | – | random accusation on day 1 (EV < 0 by design) |
| stop_early | baseline | 40 | 0 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | stops on day 1 without accusing |
| do_nothing | baseline | 40 | 0 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs: v1.4 (current rules):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| gemini:gemini-4-carbon | reported | 30 | 0 | +0.530 ± 0.138 | 0.83 | 26/30 | 9.0 | – | – | replayed, NON-judge seeds, 30 seeds, git 035105e (data/runs/committed/v1.4/inproc-gemini-4-carbon/medium) |
| opencode:google/gemini-4-carbon | reported | 30 | 0 | +0.713 ± 0.042 | 1.00 | 30/30 | 8.0 | – | – | replayed, NON-judge seeds, 30 seeds, git 035105e (data/runs/committed/v1.4/opencode-gemini-4-carbon/medium) |
| restrict_all | reported | 20 | 0 | -0.950 ± 0.098 | 0.05 | 20/20 | 7.0 | – | – | replayed, NON-judge seeds, 20 seeds, git a54c896 (data/runs/committed/v1.4/reference/restrict_all-medium-20261114-121126) |
| solver | reported | 30 | 0 | +0.645 ± 0.087 | 0.90 | 27/30 | 7.6 | – | – | replayed, NON-judge seeds, 30 seeds, git a54c896, e4b5634 (data/runs/committed/v1.4/reference/solver-medium-20261114-121126, data/runs/committed/v1.4/reference/solver-medium-seeds20to29) |
| heuristic | reported | 20 | 0 | -0.275 ± 0.361 | 0.45 | 20/20 | 11.3 | – | – | replayed, NON-judge seeds, 20 seeds, git a54c896 (data/runs/committed/v1.4/reference/heuristic-medium-20261114-121126) |
| random | reported | 20 | 0 | -0.678 ± 0.225 | 0.05 | 15/20 | 6.5 | – | – | replayed, NON-judge seeds, 20 seeds, git a54c896 (data/runs/committed/v1.4/reference/random-medium-20261114-121126) |
| stop_early | reported | 20 | 0 | -1.000 ± 0.000 | 0.00 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git a54c896 (data/runs/committed/v1.4/reference/stop_early-medium-20261114-121126); these episodes accused on day 1 under the old stop_early script (that policy is now guess_day1; current stop_early scores 0) |
| do_nothing | reported | 20 | 0 | +0.000 ± 0.000 | 0.00 | 0/20 | – | – | – | replayed, NON-judge seeds, 20 seeds, git a54c896 (data/runs/committed/v1.4/reference/do_nothing-medium-20261114-121126) |

`/ solver` is blank for reported runs: they were played on dev seeds under the team's secret, so a ratio to this invocation's judge-world solver would mislead. The paired ratios (same seeds as the solver) are in `data/runs/committed/v1.4/paired_table_gemini.md` and `docs/reports/gap.md`.

History: v1.3 (earlier rules, not comparable to the paired table):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 11 | 0 | +0.401 ± 0.417 | 0.82 | 11/11 | 8.8 | – | – | replayed, NON-judge seeds, 11 seeds, git 1724a48 (data/runs/committed/v1.3/codex-gpt-5.5-full/medium) |
| openai:gpt-5.5 | reported | 9 | 0 | +0.668 ± 0.103 | 1.00 | 9/9 | 9.9 | – | – | replayed, NON-judge seeds, 9 seeds, git 1724a48 (data/runs/committed/v1.3/gpt-5.5-full/medium) |
| restrict_all | reported | 20 | 0 | -0.950 ± 0.098 | 0.05 | 20/20 | 7.0 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/restrict_all-medium-20261114-0332) |
| solver | reported | 20 | 0 | +0.717 ± 0.052 | 1.00 | 20/20 | 7.5 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/solver-medium-20261114-0332) |
| heuristic | reported | 20 | 0 | -0.116 ± 0.361 | 0.55 | 20/20 | 11.1 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/heuristic-medium-20261114-0332) |
| random | reported | 20 | 0 | -0.678 ± 0.225 | 0.05 | 15/20 | 6.5 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/random-medium-20261114-0332) |
| stop_early | reported | 20 | 0 | -1.000 ± 0.000 | 0.00 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/stop_early-medium-20261114-0332); these episodes accused on day 1 under the old stop_early script (that policy is now guess_day1; current stop_early scores 0) |
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
| stop_early | reported | 20 | 0 | -1.000 ± 0.000 | 0.00 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/stop_early-medium-20261114-0253); these episodes accused on day 1 under the old stop_early script (that policy is now guess_day1; current stop_early scores 0) |
| do_nothing | reported | 20 | 0 | +0.000 ± 0.000 | 0.00 | 0/20 | – | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/do_nothing-medium-20261114-0253) |

## hard (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | 0 | +0.625 ± 0.088 | 0.97 | 40/40 | 7.8 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | 0 | -0.026 ± 0.192 | 0.72 | 40/40 | 14.9 | -0.04 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | 0 | -0.914 ± 0.118 | 0.05 | 40/40 | 10.0 | -1.46 | – | strongest no-canary log reader |
| random | baseline | 40 | 0 | -0.825 ± 0.119 | 0.00 | 33/40 | 6.8 | -1.32 | – | random valid tool calls |
| guess_day1 | baseline | 40 | 0 | -1.000 ± 0.000 | 0.00 | 40/40 | 1.0 | -1.60 | – | random accusation on day 1 (EV < 0 by design) |
| stop_early | baseline | 40 | 0 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | stops on day 1 without accusing |
| do_nothing | baseline | 40 | 0 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs: v1.4 (current rules):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| gemini:gemini-4-carbon | reported | 30 | 0 | +0.473 ± 0.118 | 0.93 | 29/30 | 12.7 | – | – | replayed, NON-judge seeds, 30 seeds, git 498bccd (data/runs/committed/v1.4/inproc-gemini-4-carbon/hard) |
| opencode:google/gemini-4-carbon | reported | 30 | 0 | +0.322 ± 0.199 | 0.83 | 29/30 | 13.2 | – | – | replayed, NON-judge seeds, 30 seeds, git 035105e (data/runs/committed/v1.4/opencode-gemini-4-carbon/hard) |
| restrict_all | reported | 20 | 0 | -1.000 ± 0.000 | 0.00 | 20/20 | 9.0 | – | – | replayed, NON-judge seeds, 20 seeds, git a54c896 (data/runs/committed/v1.4/reference/restrict_all-hard-20261114-121126) |
| solver | reported | 30 | 0 | +0.499 ± 0.119 | 0.97 | 30/30 | 10.6 | – | – | replayed, NON-judge seeds, 30 seeds, git a54c896, e4b5634 (data/runs/committed/v1.4/reference/solver-hard-20261114-121126, data/runs/committed/v1.4/reference/solver-hard-seeds20to29) |
| heuristic | reported | 20 | 0 | +0.186 ± 0.233 | 0.85 | 20/20 | 13.9 | – | – | replayed, NON-judge seeds, 20 seeds, git a54c896 (data/runs/committed/v1.4/reference/heuristic-hard-20261114-121126) |
| random | reported | 20 | 0 | -0.850 ± 0.161 | 0.00 | 17/20 | 8.1 | – | – | replayed, NON-judge seeds, 20 seeds, git a54c896 (data/runs/committed/v1.4/reference/random-hard-20261114-121126) |
| stop_early | reported | 20 | 0 | -1.000 ± 0.000 | 0.00 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git a54c896 (data/runs/committed/v1.4/reference/stop_early-hard-20261114-121126); these episodes accused on day 1 under the old stop_early script (that policy is now guess_day1; current stop_early scores 0) |
| do_nothing | reported | 20 | 0 | +0.000 ± 0.000 | 0.00 | 0/20 | – | – | – | replayed, NON-judge seeds, 20 seeds, git a54c896 (data/runs/committed/v1.4/reference/do_nothing-hard-20261114-121126) |

`/ solver` is blank for reported runs: they were played on dev seeds under the team's secret, so a ratio to this invocation's judge-world solver would mislead. The paired ratios (same seeds as the solver) are in `data/runs/committed/v1.4/paired_table_gemini.md` and `docs/reports/gap.md`.

History: v1.3 (earlier rules, not comparable to the paired table):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 11 | 0 | +0.655 ± 0.041 | 1.00 | 11/11 | 11.6 | – | – | replayed, NON-judge seeds, 11 seeds, git 1724a48 (data/runs/committed/v1.3/codex-gpt-5.5-full/hard) |
| openai:gpt-5.5 | reported | 8 | 0 | +0.264 ± 0.541 | 0.75 | 8/8 | 12.2 | – | – | replayed, NON-judge seeds, 8 seeds, git 1724a48 (data/runs/committed/v1.3/gpt-5.5-full/hard) |
| restrict_all | reported | 20 | 0 | -1.000 ± 0.000 | 0.00 | 20/20 | 8.0 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/restrict_all-hard-20261114-0332) |
| solver | reported | 20 | 0 | +0.592 ± 0.114 | 0.85 | 17/20 | 10.8 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/solver-hard-20261114-0332) |
| heuristic | reported | 20 | 0 | -0.322 ± 0.374 | 0.40 | 20/20 | 11.6 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/heuristic-hard-20261114-0332) |
| random | reported | 20 | 0 | -0.700 ± 0.206 | 0.00 | 14/20 | 6.6 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/random-hard-20261114-0332) |
| stop_early | reported | 20 | 0 | -0.900 ± 0.196 | 0.05 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git 0933805 (data/runs/committed/v1.3/reference/stop_early-hard-20261114-0332); these episodes accused on day 1 under the old stop_early script (that policy is now guess_day1; current stop_early scores 0) |
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
| stop_early | reported | 20 | 0 | -0.900 ± 0.196 | 0.05 | 20/20 | 1.0 | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/stop_early-hard-20261114-0253); these episodes accused on day 1 under the old stop_early script (that policy is now guess_day1; current stop_early scores 0) |
| do_nothing | reported | 20 | 0 | +0.000 ± 0.000 | 0.00 | 0/20 | – | – | – | replayed, NON-judge seeds, 20 seeds, git db104c9 (data/runs/committed/reference/do_nothing-hard-20261114-0253) |

## easy (sanity tier)

Paired runs (this invocation, same worlds):

| agent | kind | n | invalid | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | 0 | +0.763 ± 0.034 | 1.00 | 40/40 | 5.3 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | 0 | +0.650 ± 0.032 | 1.00 | 40/40 | 7.6 | 0.85 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | 0 | -0.315 ± 0.250 | 0.42 | 40/40 | 10.0 | -0.41 | – | strongest no-canary log reader |
| random | baseline | 40 | 0 | -0.800 ± 0.126 | 0.00 | 32/40 | 6.5 | -1.05 | – | random valid tool calls |
| guess_day1 | baseline | 40 | 0 | -0.700 ± 0.224 | 0.15 | 40/40 | 1.0 | -0.92 | – | random accusation on day 1 (EV < 0 by design) |
| stop_early | baseline | 40 | 0 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | stops on day 1 without accusing |
| do_nothing | baseline | 40 | 0 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |
