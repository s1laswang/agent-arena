# Canary judge table

- seeds: 40 judge seeds per tier (900000..900039)
- judge-world secret: statistical, sha256 fingerprint `562bdbec0c30` (statistical reproduction; set CANARY_WORLD_SECRET for exact numbers)
- git: `f85f21c3c37b`, generated 2026-11-14T02:53:18+0200, 2.6 s
- reward: V at accusation if correct (V starts at 1.0 and drops with every leak), -1 if wrong, 0 if no accusation
- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation
- `/ solver` = agent mean / solver mean on the same tier (ratio of means); `pass^k` only for agents with k repeated runs per seed
- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). **reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the team's worlds, so they are NOT paired with this run; compare them by mean ± CI only
- per-episode timeout guard: 60 s; no episode timed out

## medium (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.683 ± 0.070 | 0.93 | 37/40 | 7.4 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.113 ± 0.252 | 0.55 | 40/40 | 11.2 | -0.17 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.46 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.632 ± 0.175 | 0.05 | 29/40 | 4.5 | -0.93 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.950 ± 0.098 | 0.03 | 40/40 | 1.0 | -1.39 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## hard (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.617 ± 0.070 | 0.90 | 36/40 | 10.7 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.372 ± 0.254 | 0.38 | 40/40 | 11.6 | -0.60 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.62 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.850 ± 0.112 | 0.00 | 34/40 | 6.4 | -1.38 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.900 ± 0.137 | 0.05 | 40/40 | 1.0 | -1.46 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## easy (sanity tier)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.802 ± 0.029 | 1.00 | 40/40 | 4.6 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.713 ± 0.031 | 1.00 | 40/40 | 6.2 | 0.89 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.430 ± 0.244 | 0.35 | 40/40 | 10.0 | -0.54 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.703 ± 0.172 | 0.05 | 32/40 | 6.5 | -0.88 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.850 ± 0.165 | 0.07 | 40/40 | 1.0 | -1.06 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |
