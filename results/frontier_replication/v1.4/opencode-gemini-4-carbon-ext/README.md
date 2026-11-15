# v1.4 `opencode-gemini-4-carbon` hard extension replication (seeds 30-59)

Non-primary fleet replication shard for `opencode:google/gemini-4-carbon` on rules `v1.4` `hard` dev seeds `30-59`, staged outside protected `data/runs/committed/` so `make reproduce` and `results/judge_table.md` remain byte-identical to `justSilas`. The primary `n=30` (`0-29`) headline in [`data/runs/committed/v1.4/paired_table_gemini.md`](../../../../data/runs/committed/v1.4/paired_table_gemini.md) (`+0.322 +/- 0.199` vs solver `+0.499 +/- 0.119`, `65% [24%, 98%]` raw, `72% [52%, 91%]` luck-adjusted) is unchanged.

## Provenance

- **Runner and harness:** `scripts/gemini_runner.py` with `opencode` `1.19.5` over `canary.mcp_server` (`"*": "deny"`, `"canary_*": "allow"`), default `gemini-4-carbon` thinking (`includeThoughts`, medium), merged with `scripts/merge_staging.py` (`git_shas`: `2d87d0be`, `7232f800`, `ac5b5ef8`).
- **Completed fleet episodes (`n=7` of `30` planned seeds `30-59`):** seeds `[30, 34, 42, 45, 48, 57, 58]` in [`hard/episodes.jsonl`](hard/episodes.jsonl) and [`hard/meta.json`](hard/meta.json), with full transcripts in `hard/transcripts/<seed>.txt`, posterior audit in [`accuse.md`](accuse.md), and regret tags in [`tags.json`](tags.json). Four provider-quota attempts (`32, 43, 46, 59`) were excluded; `23/30` seeds were incomplete at the fleet cutoff (incomplete sequential shard caveat: shard-head seeds completed first).
- **Relation to committed `n=2` extension (`data/runs/committed/v1.4/opencode-gemini-4-carbon-ext`):** the pre-registered `30-59` extension (`f9fb7a4a`, [`docs/reports/gap.md`](../../../../docs/reports/gap.md)) stopped early at `n=2` (`seeds [34, 37]`, [`episodes.jsonl`](../../../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl)) to preserve shared carbon quota for the judge rehearsal. Seed `34` finished in both runs; per the pre-registered rule that committed valid episodes are never replaced, the deduplicated `n=8` combined extension (`[30, 34, 37, 42, 45, 48, 57, 58]`) keeps the committed `[34, 37]` episodes and adds the 6 new fleet seeds `[30, 42, 45, 48, 57, 58]`, with combined posterior audit in [`accuse_ext8_combined.md`](accuse_ext8_combined.md), regret tags in [`tags_ext8_combined.json`](tags_ext8_combined.json), and per-seed trajectory and regret analysis in [`docs/reports/frontier_ext30to59_trajectories.md`](../../../../docs/reports/frontier_ext30to59_trajectories.md).
- **Reference pairing:** paired on shared seeds against [`data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl`](../../../../data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl) (`n=30`, full `30-59` solver mean `+0.498 +/- 0.156`, luck-adjusted `+0.542`) and, for the `n=38` pool, the `0-29` primary cohorts in `data/runs/committed/v1.4/` using `scripts/paired_gemini.py` (10,000 paired bootstrap resamples, `rng_seed=0`).
- **Selection and missing-seed sensitivity (`22/30` unobserved seeds in `30-59`):** solver-observable balance tests, stratified donor imputations, and worst/best-case Manski bounds across `0-59` are audited in [`docs/reports/frontier_ext30to59_selection_sensitivity.md`](../../../../docs/reports/frontier_ext30to59_selection_sensitivity.md) and verified by [`scripts/analyze_ext30to59_selection.py`](../../../../scripts/analyze_ext30to59_selection.py) (`python scripts/analyze_ext30to59_selection.py --check` -> `PASS`).

## Paired tables in this directory

| cohort | table files | seeds | n | Gemini score +/- 95% CI | accuracy | mean day | mean P(acc) | solver, same seeds | frontier / solver [95% CI] | paired diff +/- CI | luck-adj. score | luck-adj. / solver [95% CI] |
|---|---|---|---:|---|---:|---:|---:|---:|---|---|---:|---|
| Fleet shard only | [`paired_table_fleet7.md`](paired_table_fleet7.md), [`paired_table_fleet7.json`](paired_table_fleet7.json) | `30, 34, 42, 45, 48, 57, 58` | 7 | `0.639 +/- 0.079` | 1.00 | 11.3 | 0.90 | 0.319 | `200% [116%, 837%]` | `+0.320 +/- 0.401` | 0.467 | **`109% [70%, 155%]`** |
| Deduplicated extension (committed `[34, 37]` + fleet `[30, 42, 45, 48, 57, 58]`) | [`paired_table_ext8_combined.md`](paired_table_ext8_combined.md), [`paired_table_ext8_combined.json`](paired_table_ext8_combined.json) | `30, 34, 37, 42, 45, 48, 57, 58` | 8 | `0.642 +/- 0.065` | 1.00 | 10.2 | 0.95 | 0.375 | `171% [107%, 485%]` | `+0.267 +/- 0.361` | 0.563 | **`124% [109%, 150%]`** |
| Exploratory pooled (`0-29` primary + deduplicated `n=8` extension) | [`paired_table_pooled38.md`](paired_table_pooled38.md), [`paired_table_pooled38.json`](paired_table_pooled38.json) | `0-29, 30, 34, 37, 42, 45, 48, 57, 58` | 38 | `0.390 +/- 0.163` | 0.87 | 12.5 | 0.90 | 0.473 | `82% [47%, 122%]` | `-0.083 +/- 0.178` | 0.402 | **`82% [64%, 100%]`** |

Note on small-`n` raw ratios in `30-59`: on seed `30`, `solver-hard-seeds30to59` made one of its two wrong accusations in `30-59` (`-1.000` raw, `+0.175` luck-adjusted at `P=0.858`), pulling the 7-seed and 8-seed raw solver denominators down to `0.319` and `0.375` (vs `0.498` across all 30 seeds `30-59`). Luck-adjusted scoring (`P*V - (1-P)`) removes realization noise on both sides.

## Per-seed episode summary (`30-59`)

| seed | source | Gemini score | day | accused | correct | P(accused) | Gemini luck-adj. | steps | wall_s | solver score | solver day | solver accused | solver P(acc) | solver luck-adj. |
|---:|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| 30 | fleet (`hard/episodes.jsonl`) | +0.540 | 11 | `e15` | True | 0.909 | +0.400 | 112 | 1597.9 | -1.000 | 18 | `e26` | 0.858 | +0.175 |
| 34 | committed (`opencode-gemini-4-carbon-ext`, kept in `ext8`/`pooled38`) | +0.790 | 5 | `e29` | True | 0.979 | +0.752 | 51 | 1391.8 | +0.700 | 6 | `e29` | 0.978 | +0.663 |
| 34 | fleet (`hard/episodes.jsonl`, used in `fleet7`) | +0.820 | 8 | `e29` | True | 0.650 | +0.183 | 83 | 1499.2 | +0.700 | 6 | `e29` | 0.978 | +0.663 |
| 37 | committed (`opencode-gemini-4-carbon-ext`, kept in `ext8`/`pooled38`) | +0.700 | 6 | `e25` | True | 0.981 | +0.668 | 64 | 1620.6 | +0.770 | 5 | `e25` | 0.924 | +0.635 |
| 42 | fleet (`hard/episodes.jsonl`) | +0.570 | 12 | `e19` | True | 0.969 | +0.521 | 74 | 1329.9 | +0.510 | 10 | `e19` | 0.997 | +0.505 |
| 45 | fleet (`hard/episodes.jsonl`) | +0.590 | 16 | `e11` | True | 0.973 | +0.547 | 156 | 2858.9 | +0.490 | 11 | `e11` | 0.955 | +0.423 |
| 48 | fleet (`hard/episodes.jsonl`) | +0.610 | 13 | `e10` | True | 0.916 | +0.475 | 135 | 3775.2 | +0.460 | 9 | `e10` | 0.955 | +0.394 |
| 57 | fleet (`hard/episodes.jsonl`) | +0.760 | 8 | `e29` | True | 0.970 | +0.707 | 76 | 921.8 | +0.540 | 8 | `e29` | 0.899 | +0.384 |
| 58 | fleet (`hard/episodes.jsonl`) | +0.580 | 11 | `e26` | True | 0.908 | +0.435 | 111 | 2733.8 | +0.530 | 9 | `e26` | 0.942 | +0.441 |

## Keyless verification

```bash
python scripts/verify_replay.py results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext
python scripts/check_frontier_ext_replication.py
python scripts/analyze_ext30to59_selection.py --check
```

Expected output: `7/7 episodes replay-verified` (`0` mismatches) from [`scripts/verify_replay.py`](../../../../scripts/verify_replay.py), and `OVERALL: PASS` from [`scripts/check_frontier_ext_replication.py`](../../../../scripts/check_frontier_ext_replication.py) (replays all fleet, committed extension, and `30-59` solver episodes in `canary.env.Env`, verifies `[34, 37]` + `[30, 42, 45, 48, 57, 58]` deduplication under both `n=2` and post-PR #3 `n=8` committed layouts, and checks `paired_table_fleet7.json`, `paired_table_ext8_combined.json`, `paired_table_pooled38.json`, `tags.json`, [`tags_ext8_combined.json`](tags_ext8_combined.json), `accuse.md`, and [`accuse_ext8_combined.md`](accuse_ext8_combined.md)).
