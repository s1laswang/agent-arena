# v1.4 `opencode:google/gemini-4-carbon` Hard Extension (Seeds 30-59): Per-Seed Trajectory and Regret Comparison

## 1. Scope, Provenance, and Non-Primary Cohort Caveat

This report provides a deterministic, keyless per-seed trajectory and regret comparison across all 8 replay-verified `opencode:google/gemini-4-carbon` episodes on rules `v1.4` `hard` extension dev seeds (`[30, 34, 37, 42, 45, 48, 57, 58]`), paired on identical seeds against the committed reference solver in [`data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl). Every metric below is computed offline without API calls using [`scripts/verify_replay.py`](../../scripts/verify_replay.py), [`canary/analysis/accuse.py`](../../canary/analysis/accuse.py), and [`canary/analysis/tags.py`](../../canary/analysis/tags.py) (`canary.solver.regret.attribute`).

### Two extension shards and Seed 34 overlap

- **Committed G1 extension (`n=2`, seeds `[34, 37]`):** [`data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl) (audit in [`accuse.md`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/accuse.md), regret tags in [`tags.json`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/tags.json), paired tables in [`paired_table_ext30to59.md`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_ext30to59.md) and [`paired_table_pooled0to59.md`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled0to59.md)). Pre-registered in `f9fb7a4a` ([`docs/reports/gap.md`](gap.md)) and stopped early at `n=2` (with 31 `infra:provider_quota` attempts excluded in [`meta.json`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/meta.json)) to preserve shared `gemini-4-carbon` token-per-minute quota for the Harbor judge rehearsal.
- **Fleet replication shard (`n=7`, seeds `[30, 34, 42, 45, 48, 57, 58]`):** [`results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl) (audit in [`accuse.md`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/accuse.md), regret tags in [`tags.json`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/tags.json), summary in [`README.md`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/README.md)). Staged outside protected `data/runs/committed/` using the identical `scripts/gemini_runner.py` harness (`opencode` `1.19.5` over `canary.mcp_server`, `"*": "deny"`, `"canary_*": "allow"`, default medium thinking).
- **Both runs shown for Seed 34:** Seed `34` completed independently in both G1 (`day 5`, `P=0.979`, raw `+0.790`, luck-adjusted `+0.752`) and the fleet shard (`day 8`, `P=0.650`, raw `+0.820`, luck-adjusted `+0.183`). Both trajectories are reported side-by-side below. Under the pre-registered rule that committed valid episodes are never replaced, the deduplicated `n=8` combined extension ([`paired_table_ext8_combined.md`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/paired_table_ext8_combined.md)) keeps committed G1 `[34, 37]` and adds the 6 non-overlapping fleet seeds `[30, 42, 45, 48, 57, 58]`.

### Non-primary incomplete-cohort caveat

1. **Primary headline unchanged:** The authoritative `v1.4` `hard` result remains the complete `n=30` (`0-29`) primary cohort in [`data/runs/committed/v1.4/paired_table_gemini.md`](../../data/runs/committed/v1.4/paired_table_gemini.md) and [`docs/reports/failure_analysis_v1.4.md`](failure_analysis_v1.4.md): `+0.322 +/- 0.199` vs solver `+0.499 +/- 0.119`, **`65% [24%, 98%]`** raw and **`72% [52%, 91%]`** luck-adjusted (`n=30` paired seeds).
2. **Incomplete shard selection (`8/30` seeds):** Across `30-59`, 22 of 30 planned seeds never completed a valid OpenCode episode before quota cutoff (`28/30` missing in G1; `23/30` missing in fleet, with 4 `infra:provider_quota` exclusions on seeds `32, 43, 46, 59` in [`hard/meta.json`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard/meta.json)). Sequential shard execution and quota pressure bias partial completions toward shard-head seeds and shorter episodes.
3. **Small-`n` solver denominator distortion:** Across all 30 extension seeds `30-59`, the reference solver scores `+0.498 +/- 0.156` raw and `+0.542` luck-adjusted (`27/30` correct, `2` wrong accusations on seeds `30` and `32`, `1` abstention on seed `38`), matching its `0-29` baseline (`+0.499` raw, `+0.499` luck-adjusted). Because seed `30` is included in the 7-seed and 8-seed subsets while 22 other seeds are absent, that single `-1.000` solver realization pulls the matched raw solver mean down to `+0.319` (`fleet7`) and `+0.375` (`ext8`), inflating raw ratios (`200%` and `171%`). Luck-adjusted scoring (`P*V - (1-P)`) removes realization noise on both sides (`109% [70%, 155%]` on `fleet7`, `124% [109%, 150%]` on `ext8`, and **`82% [64%, 100%]`** when pooled across all `n=38` completed seeds in [`paired_table_pooled38.md`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled38.md)).

## 2. Cohort Exploration, Posterior, and Regret Summary

| Cohort | Seeds (`n`) | Mean canaries | Mean interviews | Mean restrictions | Mean accuse day | Mean `V` | Mean `P(acc)` | Raw score +/- 95% CI | Luck-adj. score | Total regret (mean V) | Same-seed solver raw / luck-adj. | Luck-adj. / solver [95% CI] |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|---:|---|
| Committed G1 (`opencode-gemini-4-carbon-ext`) | `34, 37` (`2`) | 5.50 | 29.00 | 0.00 | 5.5 | 0.745 | 0.980 | `+0.745 +/- 0.088` | `+0.710` | `0.0826` (`0.0413`) | `+0.735` / `+0.649` | `109% [105%, 114%]` |
| Fleet shard (`frontier_replication`) | `30, 34, 42, 45, 48, 57, 58` (`7`) | 5.43 | 56.00 | 0.00 | 11.3 | 0.639 | 0.899 | `+0.639 +/- 0.079` | `+0.467` | `1.1645` (`0.1664`) | `+0.319` / `+0.427` | `109% [70%, 155%]` |
| Deduplicated extension (G1 `[34, 37]` + fleet 6) | `30, 34, 37, 42, 45, 48, 57, 58` (`8`) | 5.75 | 50.12 | 0.00 | 10.2 | 0.642 | 0.951 | `+0.642 +/- 0.065` | `+0.563` | `0.6568` (`0.0821`) | `+0.375` / `+0.453` | `124% [109%, 150%]` |
| Reference solver (matched `ext8` seeds) | `30, 34, 37, 42, 45, 48, 57, 58` (`8`) | 13.50 | 0.00 | 0.00 | 9.5 | 0.546 | 0.939 | `+0.375 +/- 0.392` | `+0.453` | `0.8582` (`0.1073`) | `+0.375` / `+0.453` | - |
| Reference solver (full `30-59` cohort) | `30-59` (`30`) | 12.17 | 0.00 | 0.00 | 8.4 (29 acc) | 0.607 | 0.962 | `+0.498 +/- 0.156` | `+0.542` | `1.9935` (`0.0665`) | `+0.498` / `+0.542` | - |
| Exploratory pooled (`0-29` primary + `ext8`) | `0-29` + `ext8` (`38`) | 7.89 | 64.21 | 0.08 | 12.5 (37 acc) | 0.555 | 0.897 | `+0.390 +/- 0.163` | `+0.402` | `5.7992` (`0.1526`) | `+0.473` / `+0.489` | **`82% [64%, 100%]`** |

Even on the 8 completed extension seeds where `opencode:google/gemini-4-carbon` went `8/8` (`9/9` across both Seed 34 runs), its action profile reproduces the exact under-exploration pattern found on `0-29` ([`docs/reports/failure_analysis_v1.4.md`](failure_analysis_v1.4.md)): it plants less than half as many canaries as the reference solver (`5.75` vs `13.50` on `ext8`), spends most of its `8/day` investigative budget on low-LR interviews (`50.1` vs `0.0`), accuses `0.75` to `1.15` days later on average, and uses `0` access restrictions.

## 3. Per-Seed Trajectory and Regret Table (All 8 Extension Seeds, Including Both Seed 34 Runs)

All 39 underlying episodes (`2/2` G1, `7/7` fleet, `30/30` solver `30-59`) pass `scripts/verify_replay.py` with `0` mismatches. `P(accused)` is the exact `SolverPolicy` posterior over the agent's own tool observations at the `accuse` step (`canary.analysis.accuse`), `V` is company value at accusation (`1 - 0.05 * leaks - 0.01 * canaries - restrictions`), luck-adjusted score is `P * V - (1 - P)`, and per-episode regret and tags come from `canary.analysis.tags` (`canary.solver.regret.attribute`).

| Seed | Source | Mole | Canaries | Interviews | Restrict | Accuse day (`who`) | `V` | `P(acc)` | Raw score | Luck-adj. | Regret (V) & tags | Steps | `wall_s` | Same-seed solver (`day`, `who`, `can`, `V`, `P`, `raw`, `luck-adj.`, `regret`, `steps`) | Gemini - solver (`raw` / `luck-adj.`) |
|---:|---|---|---:|---:|---:|---|---:|---:|---:|---:|---|---:|---:|---|---|
| 30 | fleet (`frontier_replication`) | `e15` | 6 | 61 | 0 | d11 (`e15`, ok) | 0.540 | 0.909 | `+0.540` | `+0.400` | `0.129` (`budget_waste` x1) | 112 | 1597.9 | d18, `e26` (wrong), 23 can, `V=0.370`, `P=0.858`, `-1.000`, `+0.175`, reg `0.212`, 138 st | `+1.540` / `+0.224` |
| 34 | G1 (`committed`, in `ext8`) | `e29` | 6 | 26 | 0 | d5 (`e29`, ok) | 0.790 | 0.979 | `+0.790` | `+0.752` | `0.037` (`none`) | 51 | 1391.8 | d6, `e29` (ok), 10 can, `V=0.700`, `P=0.978`, `+0.700`, `+0.663`, reg `0.046`, 53 st | `+0.090` / `+0.090` |
| 34 | fleet (`frontier_replication`, in `fleet7`) | `e29` | 3 | 49 | 0 | d8 (`e29`, ok) | 0.820 | 0.650 | `+0.820` | `+0.183` | `0.590` (`budget_waste` x1) | 83 | 1499.2 | d6, `e29` (ok), 10 can, `V=0.700`, `P=0.978`, `+0.700`, `+0.663`, reg `0.046`, 53 st | `+0.120` / `-0.480` |
| 37 | G1 (`committed`, in `ext8`) | `e25` | 5 | 32 | 0 | d6 (`e25`, ok) | 0.700 | 0.981 | `+0.700` | `+0.668` | `0.046` (`budget_waste` x1) | 64 | 1620.6 | d5, `e25` (ok), 8 can, `V=0.770`, `P=0.924`, `+0.770`, `+0.635`, reg `0.129`, 45 st | `-0.070` / `+0.032` |
| 42 | fleet (`frontier_replication`) | `e19` | 8 | 16 | 0 | d12 (`e19`, ok) | 0.570 | 0.969 | `+0.570` | `+0.521` | `0.052` (`budget_waste` x1) | 74 | 1329.9 | d10, `e19` (ok), 14 can, `V=0.510`, `P=0.997`, `+0.510`, `+0.505`, reg `0.009`, 81 st | `+0.060` / `+0.016` |
| 45 | fleet (`frontier_replication`) | `e11` | 6 | 88 | 0 | d16 (`e11`, ok) | 0.590 | 0.973 | `+0.590` | `+0.547` | `0.041` (`budget_waste` x1) | 156 | 2858.9 | d11, `e11` (ok), 16 can, `V=0.490`, `P=0.955`, `+0.490`, `+0.423`, reg `0.116`, 87 st | `+0.100` / `+0.124` |
| 48 | fleet (`frontier_replication`) | `e10` | 4 | 79 | 0 | d13 (`e10`, ok) | 0.610 | 0.916 | `+0.610` | `+0.475` | `0.131` (`budget_waste` x2) | 135 | 3775.2 | d9, `e10` (ok), 14 can, `V=0.460`, `P=0.955`, `+0.460`, `+0.394`, reg `0.099`, 75 st | `+0.150` / `+0.080` |
| 57 | fleet (`frontier_replication`) | `e29` | 4 | 38 | 0 | d8 (`e29`, ok) | 0.760 | 0.970 | `+0.760` | `+0.707` | `0.051` (`budget_waste` x1) | 76 | 921.8 | d8, `e29` (ok), 11 can, `V=0.540`, `P=0.899`, `+0.540`, `+0.384`, reg `0.174`, 66 st | `+0.220` / `+0.323` |
| 58 | fleet (`frontier_replication`) | `e26` | 7 | 61 | 0 | d11 (`e26`, ok) | 0.580 | 0.908 | `+0.580` | `+0.435` | `0.171` (`budget_waste` x1) | 111 | 2733.8 | d9, `e26` (ok), 12 can, `V=0.530`, `P=0.942`, `+0.530`, `+0.441`, reg `0.073`, 73 st | `+0.050` / `-0.007` |

### Notes on regret attribution and failure tags across `30-59`

- **All `budget_waste` tags carry `0.000` V regret:** Across G1 (`1` instance on seed `37`) and fleet (`8` instances across `7/7` seeds), `7` of the `9` `budget_waste` tags are a single day-1 `search_messages(query=" ")` call rejected with `"invalid arguments"` before Panel Fix D added `data.detail` (the model immediately retried with `query="e"`), `1` is a malformed argument key `'day_to=3,query'` on seed `42` (`t=20`, day 4), and `1` is a 9th daily action attempt `interview(employee="e28")` on seed `48` (`t=13`, day 1, `"daily action limit; call advance_day"`). On seed `48`, `79` interviews succeeded and `1` failed (`80` total calls).
- **Where real regret sits:** Almost all non-zero regret in `canary.solver.regret.attribute` comes from the `accuse` step (`max(0, V* - Q_accuse)` when `Q_continue > Q_accuse`). Across the 7 fleet episodes (`1.1645` V total regret), a single premature accusation on **Fleet Seed 34** (`0.5750` V on day 8 at `P=0.650`) accounts for **`49.4%`** of the entire shard's regret, whereas **G1 Seed 34** (`P=0.979` on day 5) incurred only `0.0177` V at `accuse` (`0.0365` V total).
- **Canary fingerprint flips on solver episodes:** None of the 9 Gemini extension episodes experienced a 5% canary fingerprint flip prior to accusation, whereas the reference solver absorbed surfaced fingerprint flips on seed `42` (`c4-2` surfaced day 8 showing `'A'` instead of `'C'`, recovering via subsequent canaries to `P=0.997` on day 10) and seed `57` (`c1-2` surfaced day 4 showing `'C'` instead of `'B'`, accusing `e29` on day 8 at `P=0.899`).

## 4. Trajectory Case Studies

### Case Study A: Seed 30 -- Carbon `+0.540` (`P=0.909` on `e15`) vs Solver `-1.000` (`P=0.858` on `e26`)

World ground truth on `hard` seed `30`: true mole `e15` (Sales), framed loud decoy `e36` (`#sales` angry posts `m1-3` and `m1-4` on day 1).

| Day | Carbon (fleet): canaries / interviews | Carbon: `P(top)` (`top`, mole?) | Carbon: `# consistent` | Carbon `V` | Solver: canaries | Solver: `P(top)` (`top`, mole?) | Solver: `# consistent` | Solver `V` |
|---:|---|---|---:|---:|---:|---|---:|---:|
| 1 | 0 / 6 | `0.025` (`e06`, no) | 40 | 1.00 | 2 | `0.025` (`e00`, no) | 40 | 0.98 |
| 2 | 0 / 5 | `0.031` (`e36`, no) | 40 | 1.00 | 2 | `0.042` (`e16`, no) | 40 | 0.96 |
| 3 | 0 / 6 | `0.047` (`e28`, no) | 40 | 1.00 | 2 | `0.047` (`e16`, no) | 40 | 0.94 |
| 4 | 1 / 5 | `0.162` (`e36`, no) | 14 | 0.94 | 2 | `0.046` (`e16`, no) | 40 | 0.92 |
| 5 | 1 / 5 | `0.214` (`e15`, yes) | 14 | 0.88 | 2 | `0.121` (`e21`, no) | 14 | 0.85 |
| 6 | 0 / 7 | `0.213` (`e15`, yes) | 14 | 0.88 | 2 | `0.222` (`e21`, no) | 7 | 0.78 |
| 7 | 1 / 5 | `0.186` (`e02`, no) | 14 | 0.77 | 1 | `0.225` (`e21`, no) | 7 | 0.77 |
| 8 | 2 / 4 | `0.365` (`e15`, yes) | 7 | 0.70 | 1 | `0.301` (`e08`, no) | 7 | 0.71 |
| 9 | 0 / 7 | `0.372` (`e15`, yes) | 7 | 0.70 | 1 | `0.333` (`e08`, no) | 7 | 0.70 |
| 10 | 1 / 5 | `0.373` (`e36`, no) | 7 | 0.64 | 1 | `0.352` (`e08`, no) | 7 | 0.64 |
| 11 | 0 / 6 | **accuse `e15`** (`0.909`, yes) | 2 (`e15, e23`) | 0.54 | 1 | `0.301` (`e08`, no) | 7 | 0.63 |
| 12-17 | - | - | - | - | 1/day (6) | `0.257-0.315` (`e08/e23/e02`) | 7 | 0.62 -> 0.47 |
| 18 | - | - | - | - | 0 | **accuse `e26`** (`0.858`, **wrong**) | 2 (`e15, e26`) | 0.37 |

- **How `gemini-4-carbon` isolated `e15` on day 11 (`+0.540` raw, `+0.400` luck-adjusted):** Carbon spent days 1-3 interviewing (`17` interviews, `0` canaries) and reading day-1 messages (`m1-3`, `m1-4`), identifying `e36` as the disgruntled `#sales` decoy. Ordinary leaks `d2-2`, `d1-2`, `d3-2`, `d5-2`, `d4-4`, and `d6-2` narrowed the consistent set to the 7 Sales recipients `{e02, e08, e15, e21, e23, e26, e36}` by day 8. On day 8 (`t=77`), Carbon planted a 6-person canary `c8-2` (`2` recipients per variant `J, K, L`) across `{e02, e08, e15, e21, e23, e26}` (excluding known decoy `e36`). `c8-2` leaked on day 9 and surfaced on day 11 with variant `'J'`, narrowing the leak-consistent set to `{e15, e23}` (tied leak log-likelihood `-12.8018`). Across 10 days of access logs, `e15` had `5` after-hours accesses (`[6 regular, 5 after-hours]`) against `1` for `e23` (`[10 regular, 1 after-hours]`), pushing `P(e15) = 0.909` (`P(e23) = 0.080`). Accusing `e15` at `V = 0.540` (`8` leaks, `6` canaries) yielded `+0.540` raw and `+0.400` luck-adjusted (`0.1286` V regret).
- **Why the reference solver accused innocent `e26` on day 18 (`-1.000` raw, `+0.175` luck-adjusted):** The solver planted `23` canaries (`2/day` on days 1-6, `1/day` on days 7-17) and narrowed the consistent set to the same 7 Sales employees by day 6. Because `careful_mole = True` on `hard` down-weights canaries relative to ordinary documents, `e15` leaked 6 ordinary documents (`d1-2, d4-4, d5-2, d5-1, d10-2, d14-2`) before leaking day-14 canary `c14` (`4` recipients: `A: 1, B: 1, C: 2`), which surfaced on day 18 with variant `'C'`. Both `e15` and `e26` shared variant `'C'`, leaving `n_consistent = 2` (`{e15, e26}`). Over 17 days, innocent `e26` had accumulated `3` framed after-hours accesses (`[13, 3]`) vs `e15`'s `1` (`[18, 1]`) and had been placed in one fewer unleaked canary (`10` vs `11`), giving `e26` both a slightly higher leak log-likelihood (`-15.2701` vs `-15.5066`) and stronger behavioural weight. That pushed `P(e26) = 0.858` (`0.8579`, vs `P(e15) = 0.113`), just crossing the solver's `0.85` accusation threshold at `V = 0.370` (`8` leaks, `23` canaries) and realizing `-1.000` raw (`+0.175` luck-adjusted, `0.2124` V regret).

### Case Study B: Seed 34 -- G1 Day 5 (`P=0.979`, Luck-Adj `+0.752`) vs Fleet Day 8 Premature Commitment (`P=0.650`, Luck-Adj `+0.183`) vs Solver (`+0.663`)

World ground truth on `hard` seed `34`: true mole `e29` (Research), framed loud decoy `e14` (`#finance` post `m1-3`). Seed `34` is the clearest controlled demonstration of how early canary exploration vs interview-heavy procrastination changes evidence quality on the exact same seed, and why luck-adjusted scoring is essential.

| Day | G1 carbon (`committed`): can / int | G1: `P(top)` (`top`) & `# consistent` | Fleet carbon: can / int | Fleet: `P(top)` (`top`) & `# consistent` | Solver: canaries | Solver: `P(top)` (`top`) & `# consistent` |
|---:|---|---|---:|---|---:|---|
| 1 | 2 / 5 | `0.025` (`e00`), 40 | 0 / 7 | `0.025` (`e01`), 40 | 2 | `0.025` (`e00`), 40 |
| 2 | 2 / 4 | `0.043` (`e08`), 40 | 0 / 6 | `0.030` (`e08`), 40 | 2 | `0.043` (`e14`), 40 |
| 3 | 2 / 4 | `0.073` (`e29`), 20 | 2 / 4 | `0.084` (`e10`), 20 | 2 | `0.089` (`e17`), 20 |
| 4 | 0 / 7 | `0.090` (`e20`), 20 | 1 / 6 | `0.088` (`e29`), 20 | 2 | `0.086` (`e29`), 20 |
| 5 | 0 / 6 | **accuse `e29`** (`0.979`), **1 (`e29`)**, `V=0.79` | 0 / 5 | `0.201` (`e10`), 7 | 2 | `0.245` (`e29`), 7 |
| 6 | - | - | 0 / 7 | `0.437` (`e29`), 7 | 0 | **accuse `e29`** (`0.978`), **1 (`e29`)**, `V=0.70` |
| 7 | - | - | 0 / 7 | `0.703` (`e29`), 7 | - | - |
| 8 | - | - | 0 / 7 | **accuse `e29`** (`0.650`), **7**, `V=0.82` | - | - |

- **G1 committed (`day 5`, `+0.790` raw, `+0.752` luck-adjusted, `0.0365` V regret):** G1 planted `2` canaries/day immediately on days 1-3 (`6` canaries total, `26` interviews, `0` invalid calls). Day-1 canary `c1-2` (`14` recipients, `e29` assigned `'A'`) was leaked by `e29` on day 3 and surfaced on day 5 alongside ordinary document `d2-1` (following `d1-1` on day 3). Intersecting `d1-1`, `d2-1`, and `c1-2 == 'A'` isolated a **singleton consistent set `['e29']`** (`n_consistent = 1`, `P(e29) = 0.979`, runner-up `e11` at `0.011`). Accusing on day 5 (`3` leaks, `6` canaries -> `V = 0.790`) achieved `+0.790` raw and `+0.752` luck-adjusted.
- **Fleet shard (`day 8`, `+0.820` raw, `+0.183` luck-adjusted, `0.5903` V regret):** Fleet spent days 1-2 interviewing (`13` interviews, `0` canaries, plus `1` invalid `search_messages(query=" ")`), planted only `3` canaries on days 3-4 (`c3, c3-2, c4`), and then planted **`0` canaries on days 5-8** while running `26` more interviews (`49` total, `21` on `e29`). With no day-1/2 canaries in play, `e29` leaked ordinary documents `d1-1` (surfaced day 3) and `d1-3` (surfaced day 5), narrowing the consistent set only to the **7 Research employees `{e04, e07, e10, e11, e12, e23, e29}`** (`n_consistent = 7`). Fleet never called `check_leak_feed` or `plant_canary` after day 5, committing on day 8 from access-log counts (`e29` had `[4 regular, 6 after-hours]` vs `<= 1` after-hours for peers) at **`P(e29) = 0.650`** (`0.6497`, runner-up `e11` at `0.073`).
- **Why raw score misleads and luck adjustment + regret catch the mistake:** Because Fleet planted `3` fewer canaries than G1 (`+0.03 V` saved) and happened to win its `65.0%` bet before day-7 leak `d7-3` reduced `V` further, Fleet scored `+0.030` *higher* raw than G1 (`+0.820` vs `+0.790`) and `+0.120` higher than the solver (`+0.700`). Under luck-adjusted scoring (`P*V - (1-P)`), carrying a `35.0%` wrong-accusation risk (`-1.0` penalty) drops Fleet to **`+0.183`** -- `-0.569` below G1 (`+0.752`) and `-0.480` below the solver (`+0.663`). Although `P = 0.650 >= 0.60` clears the discrete `premature_accusation` tag cutoff (`pe < 0.60` in `canary/solver/regret.py`), `canary.solver.regret.attribute` prices continuing with splitting canaries at `Q_continue = 0.7582` vs `Q_accuse = 0.1832`, assigning **`0.5750` V of regret** to Fleet's day-8 `accuse` call (`97.4%` of the episode's `0.5903` V regret).
- **Reference solver (`day 6`, `+0.700` raw, `+0.663` luck-adjusted, `0.0463` V regret):** The solver planted `2` canaries/day on days 1-5 (`10` canaries, `0` interviews), observed day-3 canary `c3` (`'B'`) surfacing on day 6 (`n_consistent = 1`, `['e29']`), and accused `e29` at `P = 0.978` and `V = 0.700` (`4` leaks including un-surfaced day-5 leak `d5-2`).

## 5. Keyless Reproduction Commands

All commands below run offline in a few seconds with `0` API calls using the committed JSONL files:

```bash
# 1. Replay-verify all 39 episodes (2 committed G1 + 7 fleet + 30 reference solver on seeds 30-59)
CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/verify_replay.py \
  data/runs/committed/v1.4/opencode-gemini-4-carbon-ext \
  results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext \
  data/runs/committed/v1.4/reference/solver-hard-seeds30to59

# 2. Recompute exact solver posteriors P(accused) and P(top) at accusation
CANARY_ALLOW_DEV=1 PYTHONPATH=. python -m canary.analysis.accuse \
  --runs data/runs/committed/v1.4/opencode-gemini-4-carbon-ext
CANARY_ALLOW_DEV=1 PYTHONPATH=. python -m canary.analysis.accuse \
  --runs results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext
CANARY_ALLOW_DEV=1 PYTHONPATH=. python -m canary.analysis.accuse \
  --runs data/runs/committed/v1.4/reference/solver-hard-seeds30to59

# 3. Recompute per-episode regret totals and failure tags (writes to /tmp/opencode, then clean up)
CANARY_ALLOW_DEV=1 PYTHONPATH=. python -m canary.analysis.tags \
  --runs data/runs/committed/v1.4/opencode-gemini-4-carbon-ext \
  --tier hard --out /tmp/opencode/tags_g1.json
CANARY_ALLOW_DEV=1 PYTHONPATH=. python -m canary.analysis.tags \
  --runs results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext \
  --tier hard --out /tmp/opencode/tags_fleet.json
rm -f /tmp/opencode/tags_g1.json /tmp/opencode/tags_fleet.json

# 4. Recompute paired bootstrap tables on committed extension seeds 30-59 and pooled 0-59
CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/paired_gemini.py --version v1.4 --seeds 30-59
CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/paired_gemini.py --version v1.4 --seeds 0-59
```

Expected `verify_replay.py` output: `39/39 episodes replay-verified` (`0` mismatches).
