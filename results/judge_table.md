# Canary judge table

- seeds: 40 judge seeds per tier (900000..900039)
- judge-world secret: statistical, sha256 fingerprint `f9b65910a451` (statistical reproduction; set CANARY_WORLD_SECRET for exact numbers)
- git: `33f445448246`, generated 2026-11-14T02:35:31+0200, 1.7 s
- reward: V at accusation if correct (V starts at 1.0 and drops with every leak), -1 if wrong, 0 if no accusation
- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation
- `/ solver` = agent mean / solver mean on the same tier (ratio of means); `pass^k` only for agents with k repeated runs per seed
- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). **reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the team's worlds, so they are NOT paired with this run; compare them by mean ± CI only
- per-episode timeout guard: 60 s; no episode timed out

## medium (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.546 ± 0.087 | 0.82 | 33/40 | 9.6 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.223 ± 0.257 | 0.47 | 40/40 | 11.2 | -0.41 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.83 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.627 ± 0.180 | 0.05 | 29/40 | 4.5 | -1.15 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.750 ± 0.208 | 0.12 | 40/40 | 1.0 | -1.37 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## hard (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.579 ± 0.080 | 0.85 | 34/40 | 10.6 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.289 ± 0.260 | 0.42 | 40/40 | 11.8 | -0.50 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.774 ± 0.187 | 0.12 | 40/40 | 10.0 | -1.34 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.751 ± 0.167 | 0.05 | 34/40 | 6.4 | -1.30 | – | random valid tool calls |
| stop_early | baseline | 40 | -1.000 ± 0.000 | 0.00 | 40/40 | 1.0 | -1.73 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## easy (sanity tier)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.751 ± 0.048 | 1.00 | 40/40 | 5.5 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.607 ± 0.090 | 0.97 | 40/40 | 7.6 | 0.81 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.472 ± 0.239 | 0.33 | 40/40 | 10.0 | -0.63 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.718 ± 0.159 | 0.05 | 32/40 | 6.5 | -0.96 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.850 ± 0.165 | 0.07 | 40/40 | 1.0 | -1.13 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |
