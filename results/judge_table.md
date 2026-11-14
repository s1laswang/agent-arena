# Canary judge table

- seeds: 40 judge seeds per tier (900000..900039)
- judge-world secret: statistical, sha256 fingerprint `f4dafd4db70a` (statistical reproduction; set CANARY_WORLD_SECRET for exact numbers)
- git: `849e652d947c`, generated 2026-11-14T02:45:28+0200, 2.9 s
- reward: V at accusation if correct (V starts at 1.0 and drops with every leak), -1 if wrong, 0 if no accusation
- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation
- `/ solver` = agent mean / solver mean on the same tier (ratio of means); `pass^k` only for agents with k repeated runs per seed
- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). **reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the team's worlds, so they are NOT paired with this run; compare them by mean ± CI only
- per-episode timeout guard: 60 s; no episode timed out

## medium (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.612 ± 0.086 | 0.85 | 34/40 | 7.6 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.001 ± 0.244 | 0.62 | 40/40 | 11.1 | -0.00 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.63 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.725 ± 0.140 | 0.00 | 29/40 | 4.5 | -1.18 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.900 ± 0.137 | 0.05 | 40/40 | 1.0 | -1.47 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## hard (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.619 ± 0.115 | 0.85 | 35/40 | 9.0 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.211 ± 0.261 | 0.47 | 40/40 | 11.8 | -0.34 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.61 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.800 ± 0.144 | 0.03 | 34/40 | 6.4 | -1.29 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.900 ± 0.137 | 0.05 | 40/40 | 1.0 | -1.45 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## easy (sanity tier)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.769 ± 0.038 | 1.00 | 40/40 | 5.3 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.697 ± 0.032 | 1.00 | 40/40 | 6.7 | 0.91 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.480 ± 0.235 | 0.33 | 40/40 | 10.0 | -0.62 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.725 ± 0.155 | 0.05 | 32/40 | 6.5 | -0.94 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.800 ± 0.188 | 0.10 | 40/40 | 1.0 | -1.04 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |
