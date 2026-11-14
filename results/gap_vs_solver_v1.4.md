# Gap vs reference `solver` (rules v1.4)

Generated 2026-11-14 22:30:09 EET at repo commit `633047c713`.

Command:

```
uv run --python 3.12 --extra dev python scripts/gap_vs_reference.py --ref-agent solver --procs 2
```

Inputs:

- staging: `/tmp/gapjob/staging` (160 episodes.jsonl, sha 0b11e3951dc247fe); origin copy of ~/junction-aimo-team/wt/justSilas-gemini/data/runs/staging-gemini-v1.4 @ e8a6fdf (clean)
- fleet: `/tmp/gapjob/fleet14/data/runs/committed/v1.4` (46 episodes.jsonl, sha cde9a60e795bdad4); origin copy of /tmp/fleet14 (git-archive of fleet v1.4 runs)
- bootstrap: 10000 paired resamples of seeds, numpy default_rng(20261114), percentile 95% CI

## (a) Frontier / reference, paired on the frontier's own seeds

Reference replayed in-process on 62 (tier, seed) pairs in 2.5 s (canary.eval.make_env template provider + run_episode; judge seeds excluded).

Solver reproduction check: 62 pairs compared with stored `reference/solver-*` runs, **0 mismatches**, 0 with no stored score.


Invalid (infra) episodes: dropped by gapcalc's rule (valid is False, end_reason error, or score None) in the 'invalid dropped' column; plus 40 episode files the gemini runner had already moved to staging/invalid/ (never globbed, same as gapcalc). 'dup' = seeds with more than one valid episode; the last one in gapcalc's glob order wins (same as gapcalc).

| set | tier | n | seeds | frontier | ref | ratio [95% CI] | Δ frontier−ref [95% CI] | invalid dropped | dup | wrong | abstain |
|---|---|---|---|---|---|---|---|---|---|---|---|
| carbon OpenCode (ours+fleet) | medium | 30 | 0–29 | +0.713 | +0.645 | 111% [99%, 127%] | +0.068 [-0.006, +0.151] | 0 | 0 | 0 | 0 |
| carbon OpenCode (ours+fleet) | hard | 32 | 0–34 | +0.348 | +0.458 | 76% [34%, 124%] | -0.110 [-0.322, +0.088] | 0 | 1 | 4 | 1 |
| carbon in-process (ours+fleet) | medium | 30 | 0–29 | +0.609 | +0.645 | 94% [70%, 118%] | -0.036 [-0.203, +0.101] | 0 | 10 | 1 | 1 |
| carbon in-process (ours+fleet) | hard | 30 | 0–29 | +0.546 | +0.499 | 109% [85%, 157%] | +0.047 [-0.087, +0.209] | 0 | 20 | 0 | 1 |
| 3.5-flash OpenCode (fleet) | medium | 30 | 0–29 | +0.429 | +0.645 | 66% [28%, 102%] | -0.216 [-0.480, +0.011] | 0 | 0 | 5 | 0 |
| 3.5-flash OpenCode (fleet) | hard | 30 | 0–29 | +0.535 | +0.499 | 107% [88%, 147%] | +0.036 [-0.070, +0.174] | 0 | 0 | 0 | 0 |
