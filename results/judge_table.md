# Canary judge table

- seeds: 40 judge seeds per tier (900000..900039)
- judge-world secret: statistical, sha256 fingerprint `c4a151913160` (statistical reproduction; set CANARY_WORLD_SECRET for exact numbers)
- git: `9c36218d9e81`, generated 2026-11-14T02:39:15+0200, 5.0 s
- reward: V at accusation if correct (V starts at 1.0 and drops with every leak), -1 if wrong, 0 if no accusation
- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation
- `/ solver` = agent mean / solver mean on the same tier (ratio of means); `pass^k` only for agents with k repeated runs per seed
- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). **reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the team's worlds, so they are NOT paired with this run; compare them by mean ± CI only
- per-episode timeout guard: 60 s; no episode timed out

## medium (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.588 ± 0.084 | 0.85 | 34/40 | 8.6 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.040 ± 0.247 | 0.60 | 40/40 | 11.4 | -0.07 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.915 ± 0.116 | 0.05 | 40/40 | 10.0 | -1.56 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.642 ± 0.168 | 0.05 | 29/40 | 4.5 | -1.09 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.900 ± 0.137 | 0.05 | 40/40 | 1.0 | -1.53 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## hard (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.701 ± 0.067 | 0.93 | 37/40 | 8.2 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.375 ± 0.254 | 0.38 | 40/40 | 11.7 | -0.53 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.955 ± 0.088 | 0.03 | 40/40 | 10.0 | -1.36 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.812 ± 0.130 | 0.03 | 34/40 | 6.4 | -1.16 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.950 ± 0.098 | 0.03 | 40/40 | 1.0 | -1.36 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## easy (sanity tier)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.775 ± 0.050 | 0.97 | 39/40 | 4.6 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.621 ± 0.086 | 0.97 | 40/40 | 7.3 | 0.80 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.354 ± 0.249 | 0.40 | 40/40 | 10.0 | -0.46 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.628 ± 0.191 | 0.10 | 32/40 | 6.5 | -0.81 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.750 ± 0.208 | 0.12 | 40/40 | 1.0 | -0.97 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |
