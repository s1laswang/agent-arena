# Gap vs reference `solver` (rules v1.4)

Generated 2026-11-14 22:50:29 EET at repo commit `7504551d06`.

Command:

```
uv run --python 3.12 --extra dev python scripts/gap_vs_reference.py --ref-agent solver --procs 1 --staging /tmp/gapjob/empty --fleet /tmp/gapjob/c693/data/runs/committed/v1.4 --fleet-git ~/junction-aimo-team/agent-arena:693a3b2 --staging-origin none --fleet-origin git archive 693a3b2 data/runs/committed/v1.4 --out results/gap_vs_solver_v1.4_693a3b2
```

Inputs:

- staging: `/tmp/gapjob/empty` (0 episodes.jsonl, sha e3b0c44298fc1c14); origin none
- fleet: `/tmp/gapjob/c693/data/runs/committed/v1.4` (18 episodes.jsonl, sha 4813df7cb4959416); origin git archive 693a3b2 data/runs/committed/v1.4
- bootstrap: 10000 paired resamples of seeds, numpy default_rng(20261114), percentile 95% CI

## (a) Frontier / reference, paired on the frontier's own seeds

Reference replayed in-process on 60 (tier, seed) pairs in 2.6 s (canary.eval.make_env template provider + run_episode; judge seeds excluded).

Solver reproduction check: 60 pairs compared with stored `reference/solver-*` runs, **0 mismatches**, 0 with no stored score.


Invalid (infra) episodes: dropped by gapcalc's rule (valid is False, end_reason error, or score None) in the 'invalid dropped' column; plus 0 episode files the gemini runner had already moved to staging/invalid/ (never globbed, same as gapcalc). 'dup' = seeds with more than one valid episode; team rule keeps the NEWEST run per (agent, tier, version, seed) by metadata start timestamp, else git commit time (fleet, --fleet-git), else file mtime; read order never matters. gapcalc instead keeps the last file in glob order, which can differ (see dropped list below).

| set | tier | n | seeds | frontier | ref | ratio [95% CI] | Δ frontier−ref [95% CI] | invalid dropped | dup | wrong | abstain |
|---|---|---|---|---|---|---|---|---|---|---|---|
| carbon OpenCode (ours+fleet) | medium | 30 | 0–29 | +0.713 | +0.645 | 111% [99%, 127%] | +0.068 [-0.006, +0.151] | 0 | 0 | 0 | 0 |
| carbon OpenCode (ours+fleet) | hard | 30 | 0–29 | +0.322 | +0.499 | 65% [24%, 98%] | -0.177 [-0.381, -0.008] | 0 | 0 | 4 | 1 |
| carbon in-process (ours+fleet) | medium | 30 | 0–29 | +0.530 | +0.645 | 82% [57%, 107%] | -0.115 [-0.297, +0.041] | 0 | 0 | 1 | 4 |
| carbon in-process (ours+fleet) | hard | 30 | 0–29 | +0.473 | +0.499 | 95% [63%, 142%] | -0.026 [-0.208, +0.160] | 0 | 0 | 1 | 1 |

### Dropped duplicates

