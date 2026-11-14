# Canary judge table

- seeds: 40 judge seeds per tier (900000..900039)
- judge-world secret: statistical, sha256 fingerprint `eb2e7fea6ee0` (statistical reproduction; set CANARY_WORLD_SECRET for exact numbers)
- git: `21e5b2ee0dee`, generated 2026-11-14T03:34:52+0200, 1.6 s
- reward: true V at accusation if correct (V starts at 1.0 and drops with every leak, including leaks that have not surfaced yet; v1.3 `status` shows only surfaced damage), -1 if wrong, 0 if no accusation
- accuracy = correct accusations / episodes; accused = episodes that ended in an accusation
- `/ solver` = agent mean / solver mean on the same tier (ratio of means); `pass^k` only for agents with k repeated runs per seed
- **paired runs**: reference and baselines played in this invocation on the same worlds (one secret). **reported agent runs**: frontier-agent episodes replayed from data/runs/committed/, played on the team's worlds, so they are NOT paired with this run; compare them by mean ± CI only
- per-episode timeout guard: 60 s; no episode timed out

## medium (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.612 ± 0.087 | 0.85 | 34/40 | 8.0 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.117 ± 0.231 | 0.70 | 40/40 | 11.2 | 0.19 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.911 ± 0.122 | 0.05 | 40/40 | 10.0 | -1.49 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.631 ± 0.177 | 0.05 | 29/40 | 4.5 | -1.03 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.900 ± 0.137 | 0.05 | 40/40 | 1.0 | -1.47 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| grok | reported | 5 | +0.672 ± 0.109 | 1.00 | 5/5 | 9.0 | 1.10 | – | replayed, judge seeds, 5 seeds (data/runs/committed/grok/medium) |
| opencode:openai/gpt-5.6-sol | reported | 5 | +0.124 ± 0.243 | 0.20 | 1/5 | 11.0 | 0.20 | – | replayed, NON-judge seeds, 5 seeds (data/runs/committed/opencode-gpt-5.6-sol/medium) |

## hard (headline)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.624 ± 0.105 | 0.90 | 37/40 | 9.9 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | -0.046 ± 0.258 | 0.57 | 40/40 | 11.7 | -0.07 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -1.000 ± 0.000 | 0.00 | 40/40 | 10.0 | -1.60 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.850 ± 0.112 | 0.00 | 34/40 | 6.4 | -1.36 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.900 ± 0.137 | 0.05 | 40/40 | 1.0 | -1.44 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |

Reported agent runs (replayed, unpaired, own CI):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| codex:gpt-5.5 | reported | 1 | +0.670 ± 0.000 | 1.00 | 1/1 | 13.0 | 1.07 | – | replayed, NON-judge seeds, 1 seeds (data/runs/committed/codex-gpt-5.5-smoke/hard) |
| grok | reported | 5 | +0.567 ± 0.286 | 0.80 | 4/5 | 9.5 | 0.91 | – | replayed, judge seeds, 5 seeds (data/runs/committed/grok/hard) |
| opencode:openai/gpt-5.6-sol | reported | 5 | +0.127 ± 0.249 | 0.20 | 1/5 | 14.0 | 0.20 | – | replayed, NON-judge seeds, 5 seeds (data/runs/committed/opencode-gpt-5.6-sol/hard) |

## easy (sanity tier)

Paired runs (this invocation, same worlds):

| agent | kind | n | score ± 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| solver | reference | 40 | +0.784 ± 0.033 | 1.00 | 40/40 | 5.1 | 1.00 | – | reference: tuned Bayesian canary-trap solver |
| heuristic | baseline | 40 | +0.634 ± 0.089 | 0.97 | 40/40 | 7.2 | 0.81 | – | canary bisection, no Bayes, no V timing |
| logs_only | baseline | 40 | -0.519 ± 0.231 | 0.30 | 40/40 | 10.0 | -0.66 | – | strongest no-canary log reader |
| random | baseline | 40 | -0.669 ± 0.180 | 0.07 | 32/40 | 6.5 | -0.85 | – | random valid tool calls |
| stop_early | baseline | 40 | -0.750 ± 0.208 | 0.12 | 40/40 | 1.0 | -0.96 | – | random accusation on day 1 |
| do_nothing | baseline | 40 | +0.000 ± 0.000 | 0.00 | 0/40 | – | 0.00 | – | never accuses |
