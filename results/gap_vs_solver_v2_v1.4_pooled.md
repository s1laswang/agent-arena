# Gap vs reference `solver_v2` (rules v1.4)

Generated 2026-11-14 23:12:23 EET at repo commit `ad72771328`.

Command:

```
uv run --python 3.12 --extra dev python scripts/gap_vs_reference.py --ref-agent solver_v2 --procs 2 --out results/gap_vs_solver_v2_v1.4_pooled
```

Inputs:

- staging: `/tmp/gapjob/staging` (160 episodes.jsonl, sha 0b11e3951dc247fe); origin copy of ~/junction-aimo-team/wt/justSilas-gemini/data/runs/staging-gemini-v1.4 @ e8a6fdf (clean), copied with cp -Rp (mtimes kept)
- fleet: `/tmp/gapjob/fleet14/data/runs/committed/v1.4` (46 episodes.jsonl, sha cde9a60e795bdad4); origin copy of /tmp/fleet14 = git-archive of origin/fr8/afterquery/v14-runs @ 91d57ff (all 46 episodes.jsonl byte-identical)
- bootstrap: 10000 paired resamples of seeds, numpy default_rng(20261114), percentile 95% CI

## (a) Frontier / reference, paired on the frontier's own seeds

Reference replayed in-process on 62 (tier, seed) pairs in 14.5 s (canary.eval.make_env template provider + run_episode; judge seeds excluded).

Invalid (infra) episodes: dropped by gapcalc's rule (valid is False, end_reason error, or score None) in the 'invalid dropped' column; plus 40 episode files the gemini runner had already moved to staging/invalid/ (never globbed, same as gapcalc). 'dup' = seeds with more than one valid episode; team rule keeps the NEWEST run per (agent, tier, version, seed) by metadata start timestamp, else git commit time (fleet, --fleet-git), else file mtime; read order never matters. gapcalc instead keeps the last file in glob order, which can differ (see dropped list below).

| set | tier | n | seeds | frontier | ref | ratio [95% CI] | Δ frontier−ref [95% CI] | invalid dropped | dup | wrong | abstain |
|---|---|---|---|---|---|---|---|---|---|---|---|
| carbon OpenCode (ours+fleet) | medium | 30 | 0–29 | +0.713 | +0.651 | 110% [97%, 126%] | +0.062 [-0.021, +0.147] | 0 | 0 | 0 | 0 |
| carbon OpenCode (ours+fleet) | hard | 32 | 0–34 | +0.348 | +0.537 | 65% [28%, 103%] | -0.188 [-0.405, +0.015] | 0 | 1 | 4 | 1 |
| carbon in-process (ours+fleet) | medium | 30 | 0–29 | +0.609 | +0.651 | 94% [71%, 117%] | -0.042 [-0.200, +0.095] | 0 | 10 | 1 | 1 |
| carbon in-process (ours+fleet) | hard | 30 | 0–29 | +0.529 | +0.535 | 99% [79%, 136%] | -0.005 [-0.129, +0.148] | 0 | 20 | 0 | 1 |
| 3.5-flash OpenCode (fleet) | medium | 30 | 0–29 | +0.429 | +0.651 | 66% [28%, 101%] | -0.222 [-0.486, +0.006] | 0 | 0 | 5 | 0 |
| 3.5-flash OpenCode (fleet) | hard | 30 | 0–29 | +0.535 | +0.535 | 100% [83%, 134%] | +0.000 [-0.107, +0.138] | 0 | 0 | 0 | 0 |

### Dropped duplicates

- carbon OpenCode (ours+fleet) hard seed 7: dropped score 0.69 (mtime 13:22:22) `/tmp/gapjob/staging/opencode/hard/7/episodes.jsonl`
- carbon in-process (ours+fleet) medium seed 0: dropped score 0.52 (mtime 13:41:18) `/tmp/gapjob/staging/inproc/medium/0/episodes.jsonl`
- carbon in-process (ours+fleet) medium seed 1: dropped score 0.57 (mtime 13:41:48) `/tmp/gapjob/staging/inproc/medium/1/episodes.jsonl`
- carbon in-process (ours+fleet) medium seed 2: dropped score 0.8 (mtime 13:36:57) `/tmp/gapjob/staging/inproc/medium/2/episodes.jsonl`
- carbon in-process (ours+fleet) medium seed 3: dropped score 0.0 (mtime 14:25:55) `/tmp/gapjob/staging/inproc/medium/3/episodes.jsonl`
- carbon in-process (ours+fleet) medium seed 4: dropped score 0.69 (mtime 13:39:05) `/tmp/gapjob/staging/inproc/medium/4/episodes.jsonl`
- carbon in-process (ours+fleet) medium seed 5: dropped score 0.81 (mtime 13:39:11) `/tmp/gapjob/staging/inproc/medium/5/episodes.jsonl`
- carbon in-process (ours+fleet) medium seed 6: dropped score 0.74 (mtime 13:42:39) `/tmp/gapjob/staging/inproc/medium/6/episodes.jsonl`
- carbon in-process (ours+fleet) medium seed 7: dropped score 0.0 (mtime 14:55:21) `/tmp/gapjob/staging/inproc/medium/7/episodes.jsonl`
- carbon in-process (ours+fleet) medium seed 8: dropped score 0.0 (mtime 14:50:15) `/tmp/gapjob/staging/inproc/medium/8/episodes.jsonl`
- carbon in-process (ours+fleet) medium seed 9: dropped score 0.48 (mtime 15:25:45) `/tmp/gapjob/staging/inproc/medium/9/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 0: dropped score 0.57 (mtime 12:50:35) `/tmp/gapjob/staging/inproc/hard/0/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 1: dropped score 0.55 (mtime 12:54:43) `/tmp/gapjob/staging/inproc/hard/1/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 2: dropped score 0.31 (mtime 13:15:23) `/tmp/gapjob/staging/inproc/hard/2/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 3: dropped score 0.59 (mtime 13:01:08) `/tmp/gapjob/staging/inproc/hard/3/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 4: dropped score 0.76 (mtime 12:58:57) `/tmp/gapjob/staging/inproc/hard/4/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 5: dropped score 0.1 (mtime 13:39:35) `/tmp/gapjob/staging/inproc/hard/5/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 6: dropped score -1.0 (mtime 13:25:48) `/tmp/gapjob/staging/inproc/hard/6/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 7: dropped score 0.52 (mtime 13:23:21) `/tmp/gapjob/staging/inproc/hard/7/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 8: dropped score 0.65 (mtime 13:17:23) `/tmp/gapjob/staging/inproc/hard/8/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 9: dropped score 0.74 (mtime 13:25:55) `/tmp/gapjob/staging/inproc/hard/9/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 10: dropped score 0.33 (meta.timestamp 13:57:27) `/tmp/gapjob/fleet14/data/runs/committed/v1.4/inproc-gemini-4-carbon/hard-10-19/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 11: dropped score 0.51 (meta.timestamp 13:57:27) `/tmp/gapjob/fleet14/data/runs/committed/v1.4/inproc-gemini-4-carbon/hard-10-19/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 12: dropped score 0.69 (meta.timestamp 13:57:27) `/tmp/gapjob/fleet14/data/runs/committed/v1.4/inproc-gemini-4-carbon/hard-10-19/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 13: dropped score 0.57 (meta.timestamp 13:57:27) `/tmp/gapjob/fleet14/data/runs/committed/v1.4/inproc-gemini-4-carbon/hard-10-19/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 14: dropped score 0.66 (meta.timestamp 13:57:27) `/tmp/gapjob/fleet14/data/runs/committed/v1.4/inproc-gemini-4-carbon/hard-10-19/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 15: dropped score 0.75 (meta.timestamp 13:57:27) `/tmp/gapjob/fleet14/data/runs/committed/v1.4/inproc-gemini-4-carbon/hard-10-19/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 16: dropped score 0.72 (meta.timestamp 13:57:27) `/tmp/gapjob/fleet14/data/runs/committed/v1.4/inproc-gemini-4-carbon/hard-10-19/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 17: dropped score 0.69 (meta.timestamp 13:57:27) `/tmp/gapjob/fleet14/data/runs/committed/v1.4/inproc-gemini-4-carbon/hard-10-19/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 18: dropped score 0.46 (meta.timestamp 13:57:27) `/tmp/gapjob/fleet14/data/runs/committed/v1.4/inproc-gemini-4-carbon/hard-10-19/episodes.jsonl`
- carbon in-process (ours+fleet) hard seed 19: dropped score 0.61 (meta.timestamp 13:57:27) `/tmp/gapjob/fleet14/data/runs/committed/v1.4/inproc-gemini-4-carbon/hard-10-19/episodes.jsonl`
