# Gap vs reference `solver` (rules v1.4)

Generated 2026-11-14 22:47:11 EET at repo commit `6d9cec067c`.

Command:

```
uv run --python 3.12 --extra dev python scripts/gap_vs_reference.py --ref-agent solver --procs 1 --staging /tmp/gapjob/empty --fleet /tmp/gapjob/c8fd/data/runs/committed/v1.4 --fleet-git ~/junction-aimo-team/agent-arena:8fd4dec --staging-origin none --fleet-origin git archive 8fd4dec data/runs/committed/v1.4 --out /tmp/gapjob/c8fd_check
```

Inputs:

- staging: `/tmp/gapjob/empty` (0 episodes.jsonl, sha e3b0c44298fc1c14); origin none
- fleet: `/tmp/gapjob/c8fd/data/runs/committed/v1.4` (16 episodes.jsonl, sha 2f2161d641f1e1e1); origin git archive 8fd4dec data/runs/committed/v1.4
- bootstrap: 10000 paired resamples of seeds, numpy default_rng(20261114), percentile 95% CI

## (a) Frontier / reference, paired on the frontier's own seeds

Reference replayed in-process on 60 (tier, seed) pairs in 2.7 s (canary.eval.make_env template provider + run_episode; judge seeds excluded).

Solver reproduction check: 40 pairs compared with stored `reference/solver-*` runs, **0 mismatches**, 20 with no stored score.


Invalid (infra) episodes: dropped by gapcalc's rule (valid is False, end_reason error, or score None) in the 'invalid dropped' column; plus 0 episode files the gemini runner had already moved to staging/invalid/ (never globbed, same as gapcalc). 'dup' = seeds with more than one valid episode; team rule keeps the NEWEST run per (agent, tier, version, seed) by metadata start timestamp, else git commit time (fleet, --fleet-git), else file mtime; read order never matters. gapcalc instead keeps the last file in glob order, which can differ (see dropped list below).

| set | tier | n | seeds | frontier | ref | ratio [95% CI] | Δ frontier−ref [95% CI] | invalid dropped | dup | wrong | abstain |
|---|---|---|---|---|---|---|---|---|---|---|---|
| carbon OpenCode (ours+fleet) | medium | 30 | 0–29 | +0.713 | +0.645 | 111% [99%, 127%] | +0.068 [-0.006, +0.151] | 0 | 0 | 0 | 0 |
| carbon OpenCode (ours+fleet) | hard | 30 | 0–29 | +0.322 | +0.499 | 65% [24%, 98%] | -0.177 [-0.381, -0.008] | 0 | 0 | 4 | 1 |
| carbon in-process (ours+fleet) | medium | 30 | 0–29 | +0.530 | +0.645 | 82% [57%, 107%] | -0.115 [-0.297, +0.041] | 0 | 0 | 1 | 4 |
| carbon in-process (ours+fleet) | hard | 30 | 0–29 | +0.473 | +0.499 | 95% [63%, 142%] | -0.026 [-0.208, +0.160] | 0 | 0 | 1 | 1 |

### Dropped duplicates


## Reconciliation with docs/reports/gap.md (671ed96, runs committed at 8fd4dec)

Frontier means match exactly (OpenCode medium 0.713, hard 0.322; in-process 0.530 / 0.473). The ratios differ because
the committed table divides the 30-seed frontier mean by the stored solver mean on seeds 0–19 only (0.717 medium,
0.464 hard: 8fd4dec has solver reference runs only for 0–19). This script replays the solver on all 30 paired seeds
(hard 0.499, medium 0.645; the 40 stored scores reproduce exactly), so OpenCode hard is 65% [24%, 98%] paired vs
60% [1%, 103%] committed. The luck-adjusted column (68% [43%, 91%]) needs posterior replay and is not computed here.
