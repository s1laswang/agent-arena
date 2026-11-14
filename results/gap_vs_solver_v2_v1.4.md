# Gap vs reference `solver_v2` (rules v1.4)

Generated 2026-11-14 23:01:10 EET at repo commit `cce497053c`.

Command:

```
uv run --python 3.12 --extra dev python scripts/gap_vs_reference.py --ref-agent solver_v2 --procs 2 --staging /tmp/gapjob/empty --fleet /tmp/gapjob/c693/data/runs/committed/v1.4 --fleet-git ~/junction-aimo-team/agent-arena:693a3b2 --staging-origin none --fleet-origin git archive 693a3b2 data/runs/committed/v1.4 (committed baseline) --check-solver --fresh 400 --seed0 9000 --tiers medium,hard
```

Inputs:

- staging: `/tmp/gapjob/empty` (0 episodes.jsonl, sha e3b0c44298fc1c14); origin none
- fleet: `/tmp/gapjob/c693/data/runs/committed/v1.4` (18 episodes.jsonl, sha 4813df7cb4959416); origin git archive 693a3b2 data/runs/committed/v1.4 (committed baseline)
- bootstrap: 10000 paired resamples of seeds, numpy default_rng(20261114), percentile 95% CI

## (a) Frontier / reference, paired on the frontier's own seeds

Reference replayed in-process on 60 (tier, seed) pairs in 1.8 s (canary.eval.make_env template provider + run_episode; judge seeds excluded).

Solver reproduction check: 60 pairs compared with stored `reference/solver-*` runs, **0 mismatches**, 0 with no stored score.


Invalid (infra) episodes: dropped by gapcalc's rule (valid is False, end_reason error, or score None) in the 'invalid dropped' column; plus 0 episode files the gemini runner had already moved to staging/invalid/ (never globbed, same as gapcalc). 'dup' = seeds with more than one valid episode; team rule keeps the NEWEST run per (agent, tier, version, seed) by metadata start timestamp, else git commit time (fleet, --fleet-git), else file mtime; read order never matters. gapcalc instead keeps the last file in glob order, which can differ (see dropped list below).

| set | tier | n | seeds | frontier | ref | ratio [95% CI] | Δ frontier−ref [95% CI] | invalid dropped | dup | wrong | abstain |
|---|---|---|---|---|---|---|---|---|---|---|---|
| carbon OpenCode (ours+fleet) | medium | 30 | 0–29 | +0.713 | +0.653 | 109% [97%, 127%] | +0.060 [-0.025, +0.149] | 0 | 0 | 0 | 0 |
| carbon OpenCode (ours+fleet) | hard | 30 | 0–29 | +0.322 | +0.476 | 68% [26%, 111%] | -0.154 [-0.359, +0.042] | 0 | 0 | 4 | 1 |
| carbon in-process (ours+fleet) | medium | 30 | 0–29 | +0.530 | +0.653 | 81% [58%, 102%] | -0.122 [-0.279, +0.014] | 0 | 0 | 1 | 4 |
| carbon in-process (ours+fleet) | hard | 30 | 0–29 | +0.473 | +0.476 | 99% [65%, 161%] | -0.003 [-0.196, +0.195] | 0 | 0 | 1 | 1 |

### Dropped duplicates


## (b) `solver_v2` vs solver on fresh seeds 9000–9399

| tier | n | ref mean [CI] | solver mean [CI] | Δ ref−solver [CI] | ratio [CI] | ref acc / abstain | solver acc / abstain |
|---|---|---|---|---|---|---|---|
| medium | 400 | +0.620 [+0.595, +0.644] | +0.617 [+0.592, +0.641] | +0.003 [-0.028, +0.034] | 101% [96%, 106%] | 100% / 10% | 100% / 12% |
| hard | 400 | +0.571 [+0.538, +0.600] | +0.561 [+0.527, +0.593] | +0.010 [-0.018, +0.038] | 102% [97%, 107%] | 97% / 1% | 96% / 1% |
