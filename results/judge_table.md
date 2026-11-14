# Canary judge table

- seeds: 40 judge seeds per tier (900000..900039)
- judge-world secret: statistical, sha256 fingerprint `a92dd5580876` (statistical reproduction; set CANARY_WORLD_SECRET for exact numbers)
- git: `ecb986bacfb3`, generated 2026-11-14T02:47:16+0200, 2.3 s
- reward: V at accusation if correct (V starts at 1.0 and drops with every leak), -1 if wrong, 0 if no accusation
- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation
- `/ solver` = agent mean / solver mean on the same tier (ratio of means); `pass^k` only for agents with k repeated runs per seed
- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). **reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the team's worlds, so they are NOT paired with this run; compare them by mean ± CI only
- per-episode timeout guard: 60 s; no episode timed out

## medium (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.658 ± 0.069 | 0.93 | 37/40 | 8.2 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.077 ± 0.250 | 0.57 | 40/40 | 11.2 | -0.12 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.913 ± 0.119 | 0.05 | 40/40 | 10.0 | -1.39 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.725 ± 0.140 | 0.00 | 29/40 | 4.5 | -1.10 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.800 ± 0.188 | 0.10 | 40/40 | 1.0 | -1.21 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## hard (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.555 ± 0.096 | 0.78 | 31/40 | 10.0 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.041 ± 0.259 | 0.57 | 40/40 | 11.7 | -0.07 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.80 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.817 ± 0.126 | 0.03 | 34/40 | 6.4 | -1.47 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.900 ± 0.137 | 0.05 | 40/40 | 1.0 | -1.62 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## easy (sanity tier)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.798 ± 0.028 | 1.00 | 40/40 | 4.7 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.707 ± 0.032 | 1.00 | 40/40 | 6.6 | 0.89 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.676 ± 0.203 | 0.20 | 40/40 | 10.0 | -0.85 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.750 ± 0.153 | 0.03 | 32/40 | 6.5 | -0.94 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.850 ± 0.165 | 0.07 | 40/40 | 1.0 | -1.07 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |
