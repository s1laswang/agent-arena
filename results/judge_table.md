# Canary judge table

- seeds: 40 judge seeds per tier (900000..900039)
- judge-world secret: statistical, sha256 fingerprint `d7e45dc56304` (statistical reproduction; set CANARY_WORLD_SECRET for exact numbers)
- git: `edffdace281c`, generated 2026-11-14T02:56:05+0200, 3.9 s
- reward: V at accusation if correct (V starts at 1.0 and drops with every leak), -1 if wrong, 0 if no accusation
- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation
- `/ solver` = agent mean / solver mean on the same tier (ratio of means); `pass^k` only for agents with k repeated runs per seed
- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). **reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the team's worlds, so they are NOT paired with this run; compare them by mean ± CI only
- per-episode timeout guard: 60 s; no episode timed out

## medium (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.648 ± 0.074 | 0.90 | 36/40 | 8.0 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.046 ± 0.242 | 0.65 | 40/40 | 11.1 | 0.07 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.958 ± 0.082 | 0.03 | 40/40 | 10.0 | -1.48 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.588 ± 0.188 | 0.07 | 29/40 | 4.5 | -0.91 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.950 ± 0.098 | 0.03 | 40/40 | 1.0 | -1.47 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## hard (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.624 ± 0.079 | 0.88 | 35/40 | 9.5 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.262 ± 0.256 | 0.45 | 40/40 | 11.5 | -0.42 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.865 ± 0.149 | 0.07 | 40/40 | 10.0 | -1.39 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.800 ± 0.144 | 0.03 | 34/40 | 6.4 | -1.28 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.850 ± 0.165 | 0.07 | 40/40 | 1.0 | -1.36 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| frontier agents (gpt-5.5, gpt-5.6-sol) | reported | 0 | pending | – | – | – | – | – | pending: no data/runs/committed/**/episodes.jsonl yet |

## easy (sanity tier)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.774 ± 0.045 | 1.00 | 40/40 | 5.2 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.666 ± 0.039 | 1.00 | 40/40 | 7.0 | 0.86 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.629 ± 0.217 | 0.23 | 40/40 | 10.0 | -0.81 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.722 ± 0.157 | 0.05 | 32/40 | 6.5 | -0.93 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.700 ± 0.224 | 0.15 | 40/40 | 1.0 | -0.90 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |
