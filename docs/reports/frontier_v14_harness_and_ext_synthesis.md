# v1.4 Frontier Synthesis: Harness Gap, Model-Tier Gap, and 30-59 Extension Head-to-Head

## 1. Scope, Primary Headline Rule, and Provenance

This report synthesizes seed-paired head-to-head win/tie/loss (`W-T-L`) outcomes across rules `v1.4` along three axes: (1) the **harness gap** (`opencode:google/gemini-4-carbon` over MCP vs `inproc-gemini-4-carbon` full-history thought-signature replay on seeds `0-29`), (2) the **model-tier gap** (`opencode:google/gemini-4-carbon` vs `opencode:google/gemini-3.5-flash` on seeds `0-29`), and (3) **out-of-sample `30-59` extension comparisons** (`ext8` `[30, 34, 37, 42, 45, 48, 57, 58]` and `pooled38` against both `solver` and `heuristic`). Every number in this report is computed deterministically with `0` API calls by [`scripts/analyze_v14_harness_and_family_gap.py`](../../scripts/analyze_v14_harness_and_family_gap.py) and verified in [`tests/test_v14_harness_and_ext_synthesis.py`](../../tests/test_v14_harness_and_ext_synthesis.py).

### Primary `0-29` headline rule (unchanged)

- **Authoritative `v1.4` `hard` headline (`n=30`, seeds `0-29`, MCP tools only):** OpenCode + `gemini-4-carbon` over MCP scores `+0.322 +/- 0.199` vs reference solver `+0.499 +/- 0.119` (paired diff `-0.177 +/- 0.194`), giving **`65% [24%, 98%]`** raw (`64.6%`) and **`72% [52%, 91%]`** luck-adjusted (`72.0%`, `+0.360` vs `+0.499`) in [`data/runs/committed/v1.4/paired_table_gemini.md`](../../data/runs/committed/v1.4/paired_table_gemini.md), [`docs/reports/gap.md`](gap.md), and [`docs/reports/failure_analysis_v1.4.md`](failure_analysis_v1.4.md) (see [`docs/reports/gap.md`](gap.md) for cross-family `opencode-gpt-5.5` and Harbor judge-path rehearsal comparisons).
- **Extension role (`30-59` exploratory only):** Per the pre-registered extension rule in [`docs/reports/gap.md`](gap.md), partial `30-59` OpenCode runs (`8/30` seeds completed before shared carbon quota cutoffs) are reported separately (`ext8`) and pooled (`pooled38`) for out-of-sample checks, and never replace the complete `n=30` (`0-29`) primary headline.

### Input artifacts and forward-compatibility

- **Primary `0-29` cohorts (`hard`, `n=30` each):** [`data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl), [`data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl`](../../data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl), and [`data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl), plus `medium` harness cohorts audited via [`docs/reports/harness.md`](harness.md) and [`scripts/paired_gemini.py`](../../scripts/paired_gemini.py).
- **Reference `solver` (`n=60`, seeds `0-59`) and `heuristic` (`n=60`, seeds `0-59`):** solver shards [`data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl) (`0-19`), [`data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl) (`20-29`), and [`data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl) (`30-59`); committed heuristic shard [`data/runs/committed/v1.4/reference/heuristic-hard-20261114-121126/episodes.jsonl`](../../data/runs/committed/v1.4/reference/heuristic-hard-20261114-121126/episodes.jsonl) (`0-19`, verified `20/20` bit-exact against `Heuristic(seed=s)` in [`canary/baselines.py`](../../canary/baselines.py)) extended deterministically to `20-59` with `0` API calls. Luck-adjusted scores (`P*V - (1-P)` on accused episodes, `0.0` on abstentions) use [`canary/analysis/accuse.py`](../../canary/analysis/accuse.py).
- **Extension `ext8` (`[30, 34, 37, 42, 45, 48, 57, 58]`) and optional cross-family runs (`opencode-gpt-5.5`, `argon`, `hydrogen`):** combines [`data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl) (`G1` `n=2` on `justSilas` or `n=8` on PR #3 `v14-runs`) with `results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl` (`n=7` fleet shard-head episodes), enforcing `G1` precedence on overlapping seed `34` (`day 5`, raw `+0.790`, luck-adjusted `+0.752` over fleet `day 8`, raw `+0.820`, luck-adjusted `+0.183`). When `opencode-gpt-5.5`, `opencode-gemini-4-argon`, or `opencode-gemini-4-hydrogen` exist under `--committed-root`, `--json` automatically includes their cross-family and head-to-head rows without altering this report's core tables.

## 2. Primary `0-29` Cohort Summary and Seed-Paired Head-to-Head Matrices (`v1.4` `hard`)

### Table 2A: Primary `0-29` `hard` cohort scoreboard (paired with `solver` on identical seeds)

| Cohort (`v1.4` `hard`) | `n` | Raw +/- 95% CI | Raw / solver [95% CI] | Luck-adj. +/- 95% CI | Luck-adj. / solver [95% CI] | Acc. (`ok/w/ab`) | Mean `P(acc)` | Day (`acc`) | Canaries / Interviews |
|---|---:|---|---|---|---|---|---:|---:|---|
| OpenCode + gemini-4-carbon over MCP (judges' shape) | 30 | `+0.322 +/- 0.199` | `64.6%` `[24%, 98%]` | `+0.360 +/- 0.105` | **`72.0%`** `[52%, 91%]` | `83.3%` (`25/4/1`) | `0.882` | `13.2` | `8.5` / `68.0` |
| in-process gemini-4-carbon (thought-signature replay) | 30 | `+0.473 +/- 0.118` | `94.8%` `[62%, 140%]` | `+0.421 +/- 0.086` | **`84.3%`** `[65%, 106%]` | `93.3%` (`28/1/1`) | `0.930` | `12.7` | `8.6` / `57.3` |
| OpenCode + gemini-3.5-flash over MCP (lower tier) | 30 | `+0.373 +/- 0.177` | `74.7%` `[36%, 123%]` | `+0.110 +/- 0.219` | **`22.0%`** `[-23%, 63%]` | `90.0%` (`27/3/0`) | `0.710` | `12.7` | `12.4` / `0.7` |
| reference solver | 30 | `+0.499 +/- 0.119` | - | `+0.499 +/- 0.064` | - | `96.7%` (`29/1/0`) | `0.965` | `10.6` | `14.1` / `0.0` |
| heuristic (bisection baseline) | 30 | `+0.086 +/- 0.204` | `17.2%` `[-26%, 60%]` | `+0.052 +/- 0.145` | **`10.5%`** `[-20%, 37%]` | `80.0%` (`24/6/0`) | `0.775` | `14.4` | `23.0` / `0.0` |
| heuristic (committed shard seeds 0-19) | 20 | `+0.186 +/- 0.233` | `40.0%` `[-12%, 108%]` | `+0.095 +/- 0.181` | **`19.3%`** `[-19%, 54%]` | `85.0%` (`17/3/0`) | `0.787` | `13.9` | `21.8` / `0.0` |

### Table 2B: Seed-paired `5x5` win-tie-loss matrix on `v1.4` `hard` seeds `0-29` (`row` vs `column`, `n=30`)

| Row vs Col (`raw W-T-L` / `luck-adj. W-T-L`) | OC carbon | In-proc carbon | OC 3.5-flash | Solver | Heuristic |
|---|---|---|---|---|---|
| **OC carbon** | `0-30-0` | `16-0-14` / **`12-0-18`** | `14-1-15` / **`17-0-13`** | `13-1-16` / **`10-0-20`** | `21-1-8` / **`24-0-6`** |
| **In-proc carbon** | `14-0-16` / **`18-0-12`** | `0-30-0` | `17-0-13` / **`20-0-10`** | `16-0-14` / **`15-0-15`** | `24-0-6` / **`25-0-5`** |
| **OC 3.5-flash** | `15-1-14` / **`13-0-17`** | `13-0-17` / **`10-0-20`** | `0-30-0` | `12-0-18` / **`11-0-19`** | `23-1-6` / **`19-0-11`** |
| **Solver** | `16-1-13` / **`20-0-10`** | `14-0-16` / **`15-0-15`** | `18-0-12` / **`19-0-11`** | `0-30-0` | `23-0-7` / **`25-0-5`** |
| **Heuristic** | `8-1-21` / **`6-0-24`** | `6-0-24` / **`5-0-25`** | `6-1-23` / **`11-0-19`** | `7-0-23` / **`5-0-25`** | `0-30-0` |

### Table 2C: Pairwise head-to-head differences and sign-flip `p`-values on `v1.4` `hard` (`0-29`, `n=30`)

| Matchup (`A` minus `B`, `n=30`) | Raw `W-T-L` (`win%`) | Raw diff +/- 95% CI | Raw sign-flip `p` | Luck-adj. `W-T-L` (`win%`) | Luck-adj. diff +/- 95% CI | Luck-adj. sign-flip `p` |
|---|---|---|---:|---|---|---:|
| OC carbon vs Solver | `13-1-16` (`45.0%`) | `-0.177 +/- 0.194` | `0.0927` | **`10-0-20`** (`33.3%`) | **`-0.140 +/- 0.104`** | `0.0102` |
| In-proc carbon vs Solver | `16-0-14` (`53.3%`) | `-0.026 +/- 0.184` | `0.7890` | **`15-0-15`** (`50.0%`) | **`-0.078 +/- 0.108`** | `0.1654` |
| OC 3.5-flash vs Solver | `12-0-18` (`40.0%`) | `-0.126 +/- 0.221` | `0.2809` | **`11-0-19`** (`36.7%`) | **`-0.389 +/- 0.220`** | `0.0013` |
| Heuristic vs Solver | `7-0-23` (`23.3%`) | `-0.413 +/- 0.250` | `0.0025` | **`5-0-25`** (`16.7%`) | **`-0.447 +/- 0.158`** | `0.0001` |
| OC carbon vs In-proc carbon | `16-0-14` (`53.3%`) | `-0.151 +/- 0.229` | `0.2190` | **`12-0-18`** (`40.0%`) | **`-0.061 +/- 0.142`** | `0.4087` |
| OC carbon vs OC 3.5-flash | `14-1-15` (`48.3%`) | `-0.051 +/- 0.239` | `0.6885` | **`17-0-13`** (`56.7%`) | **`+0.250 +/- 0.221`** | `0.0349` |
| In-proc carbon vs OC 3.5-flash | `17-0-13` (`56.7%`) | `+0.100 +/- 0.197` | `0.3448` | **`20-0-10`** (`66.7%`) | **`+0.311 +/- 0.232`** | `0.0135` |
| OC carbon vs Heuristic | `21-1-8` (`71.7%`) | `+0.237 +/- 0.256` | `0.0814` | **`24-0-6`** (`80.0%`) | **`+0.307 +/- 0.177`** | `0.0014` |
| In-proc carbon vs Heuristic | `24-0-6` (`80.0%`) | `+0.387 +/- 0.221` | `0.0013` | **`25-0-5`** (`83.3%`) | **`+0.369 +/- 0.166`** | `0.0001` |
| OC 3.5-flash vs Heuristic | `23-1-6` (`78.3%`) | `+0.287 +/- 0.263` | `0.0413` | **`19-0-11`** (`63.3%`) | **`+0.058 +/- 0.265`** | `0.6661` |

## 3. Harness Gap Analysis: OpenCode over MCP vs In-Process Thought-Signature Replay (`0-29`)

### Table 3A: Cross-tier harness comparison (`gemini-4-carbon`, seeds `0-29`, `n=30` per tier)

| Tier | OpenCode raw / luck-adj. | In-proc raw / luck-adj. | Raw `W-T-L` (`OC - IP`) | Raw diff +/- 95% CI | Luck-adj. `W-T-L` (`OC - IP`) | Luck-adj. diff +/- 95% CI | OC vs IP canaries |
|---|---|---|---|---|---|---|---:|
| `hard` | `+0.322` / `+0.360` | `+0.473` / `+0.421` | `16-0-14` | `-0.151 +/- 0.229` | **`12-0-18`** | **`-0.061 +/- 0.142`** | `8.5` vs `8.6` |
| `medium` | `+0.713` / `+0.652` | `+0.530` / `+0.479` | `18-2-10` | `+0.183 +/- 0.143` | **`18-1-11`** | **`+0.173 +/- 0.146`** | `5.8` vs `6.9` |

1. **Why OpenCode leads `16-0-14` in raw per-seed wins on `hard` yet trails by `-0.151` in mean score:** On the `24` `hard` seeds where both harnesses accused the true mole, OpenCode averages `+0.539` vs in-process `+0.543`. The entire `-0.151` raw gap comes from tail losses (`4` wrong `-1.0` accusations on OpenCode vs `1` on in-process). Decomposing `raw_diff = luck_adjusted_diff + luck_windfall_delta` gives `-0.151 = -0.061 + (-0.089)`: `59.2%` of the raw harness gap is realized luck (OpenCode `-0.037`/seed vs in-process `+0.052`/seed), leaving a non-significant `-0.061 +/- 0.142` luck-adjusted difference (`p = 0.4087`).
2. **Identical exploration profile, reversals across tiers (`medium` `+0.183` raw / `+0.173` luck-adjusted for OpenCode):** On `hard`, both harnesses plant almost identical canary counts (`8.5` vs `8.6` against solver `14.1`) and over-invest in interviews (`68.0` vs `57.3`), while OpenCode commits slightly earlier in posterior (`mean P(accused) = 0.882` vs `0.930`, `10` vs `4` sub-`0.85` accusations). On `medium` (`solver = +0.645`), the sign flips decisively in OpenCode's favor (`18-2-10` raw, `18-1-11` luck-adjusted, `p = 0.0246`), confirming that the OpenCode MCP interface itself imposes no structural ceiling (consistent with cross-family and Harbor container comparisons in [`docs/reports/gap.md`](gap.md)).

## 4. Model-Tier Gap Analysis: `gemini-4-carbon` vs `gemini-3.5-flash` (`0-29` `hard`)

- **Why raw scores invert while luck-adjusted scores separate by `+0.250 +/- 0.221` V/seed (`+50.0` pp of solver):** On `0-29` `hard`, `gemini-3.5-flash` posts `+0.373` raw vs `gemini-4-carbon` `+0.322` (`14-1-15`, diff `-0.051 +/- 0.239`) only because `3.5-flash` gambled at `mean P(accused) = 0.710` (`12/30` accusations below `P = 0.85`, `10/30` negative-EV gambles). Its posteriors priced `8.71` expected wrong accusations, yet only `3` realized wrong (`+0.263` V/seed luck windfall).
- **True decision-quality gap (`72.0%` vs `22.0%` of solver):** Removing realization luck (`P*V - (1-P)`), `gemini-4-carbon` (`+0.360`, **`72.0%`** of solver) outperforms `gemini-3.5-flash` (`+0.110`, **`22.0%`** of solver) by **`+0.250 +/- 0.221`** (`17-0-13` W-T-L, two-sided sign-flip `p = 0.0349`), directly validating why Canary pairs raw scores with solver-posterior luck-adjusted EV.

## 5. Out-of-Sample `30-59` Extension Comparison (`ext8` and `pooled38` vs `solver` and `heuristic`)

### Table 5A: Extension and pooled cohort metrics (`v1.4` `hard`, exploratory non-primary)

| Cohort | Seeds (`n`) | Raw +/- 95% CI | Raw / solver [95% CI] | Luck-adj. +/- 95% CI | Luck-adj. / solver [95% CI] | Acc. (`ok/n`) | Mean `P(acc)` | Day (`acc`) |
|---|---|---|---:|---|---:|---|---:|---:|
| OpenCode + gemini-4-carbon G1 pre-stop ([34, 37]) | `[34, 37]` (`2`) | `+0.745 +/- 0.088` | `101.4%` `[91%, 113%]` | `+0.710 +/- 0.083` | **`109.4%`** `[105%, 114%]` | `100.0%` (`2/2`) | `0.980` | `5.5` |
| OpenCode + gemini-4-carbon pooled G1 (0-29 + [34, 37]) | `0-29 + [34, 37]` (`32`) | `+0.349 +/- 0.190` | `67.9%` `[32%, 100%]` | `+0.381 +/- 0.103` | **`75.0%`** `[56%, 93%]` | `84.4%` (`27/32`) | `0.888` | `12.7` |
| OpenCode + gemini-4-carbon deduplicated ext8 | `ext8` (`8`) | `+0.642 +/- 0.065` | `171.3%` `[107%, 485%]` | `+0.563 +/- 0.091` | **`124.4%`** `[109%, 150%]` | `100.0%` (`8/8`) | `0.951` | `10.2` |
| reference solver on ext8 seeds | `ext8` (`8`) | `+0.375 +/- 0.392` | - | `+0.453 +/- 0.107` | - | `87.5%` (`7/8`) | `0.939` | `9.5` |
| heuristic on ext8 seeds | `ext8` (`8`) | `+0.120 +/- 0.324` | `32.0%` `[-67%, 187%]` | `+0.001 +/- 0.324` | **`0.3%`** `[-83%, 52%]` | `87.5%` (`7/8`) | `0.779` | `16.4` |
| OpenCode + gemini-4-carbon pooled38 (0-29 + ext8) | `0-29 + ext8` (`38`) | `+0.390 +/- 0.163` | `82.4%` `[47%, 122%]` | `+0.402 +/- 0.089` | **`82.2%`** `[64%, 100%]` | `86.8%` (`33/38`) | `0.897` | `12.5` |
| reference solver on pooled38 seeds | `0-29 + ext8` (`38`) | `+0.473 +/- 0.123` | - | `+0.489 +/- 0.055` | - | `94.7%` (`36/38`) | `0.960` | `10.4` |
| heuristic on pooled38 seeds | `0-29 + ext8` (`38`) | `+0.093 +/- 0.173` | `19.6%` `[-18%, 59%]` | `+0.042 +/- 0.131` | **`8.5%`** `[-19%, 33%]` | `81.6%` (`31/38`) | `0.776` | `14.8` |
| reference solver on all extension seeds (30-59) | `30-59` (`30`) | `+0.498 +/- 0.156` | - | `+0.542 +/- 0.062` | - | `90.0%` (`27/30`) | `0.962` | `8.4` |
| heuristic on all extension seeds (30-59) | `30-59` (`30`) | `+0.118 +/- 0.163` | `23.6%` `[-11%, 60%]` | `+0.062 +/- 0.125` | **`11.4%`** `[-13%, 32%]` | `86.7%` (`26/30`) | `0.823` | `15.6` |

### Table 5B: Extension and pooled head-to-head win-tie-loss summary

| Matchup (`A` minus `B`) | `n` | Raw `W-T-L` (`win%`) | Raw diff +/- 95% CI | Luck-adj. `W-T-L` (`win%`) | Luck-adj. diff +/- 95% CI | Luck-adj. sign-flip `p` |
|---|---:|---|---|---|---|---:|
| OC carbon (`ext8`) vs Solver (`ext8`) | 8 | `7-0-1` (`87.5%`) | `+0.267 +/- 0.361` | **`7-0-1`** (`87.5%`) | **`+0.110 +/- 0.078`** | `0.0156` |
| OC carbon (`ext8`) vs Heuristic (`ext8`) | 8 | `8-0-0` (`100.0%`) | `+0.522 +/- 0.313` | **`8-0-0`** (`100.0%`) | **`+0.562 +/- 0.311`** | `0.0078` |
| Solver (`ext8`) vs Heuristic (`ext8`) | 8 | `7-0-1` (`87.5%`) | `+0.255 +/- 0.502` | **`8-0-0`** (`100.0%`) | **`+0.451 +/- 0.293`** | `0.0078` |
| OC carbon (`pooled38`) vs Solver (`pooled38`) | 38 | `20-1-17` (`53.9%`) | `-0.083 +/- 0.178` | **`17-0-21`** (`44.7%`) | **`-0.087 +/- 0.089`** | `0.0637` |
| OC carbon (`pooled38`) vs Heuristic (`pooled38`) | 38 | `29-1-8` (`77.6%`) | `+0.297 +/- 0.214` | **`32-0-6`** (`84.2%`) | **`+0.361 +/- 0.156`** | `0.0002` |
| Solver (`pooled38`) vs Heuristic (`pooled38`) | 38 | `30-0-8` (`78.9%`) | `+0.380 +/- 0.222` | **`33-0-5`** (`86.8%`) | **`+0.448 +/- 0.137`** | `0.0001` |
| Solver (`30-59`) vs Heuristic (`30-59`) | 30 | `27-0-3` (`90.0%`) | `+0.380 +/- 0.227` | **`29-0-1`** (`96.7%`) | **`+0.480 +/- 0.134`** | `0.0001` |
| OC carbon (`0-19`) vs Heuristic committed (`0-19`) | 20 | `12-0-8` (`60.0%`) | `+0.090 +/- 0.333` | **`15-0-5`** (`75.0%`) | **`+0.240 +/- 0.227`** | `0.0486` |

### Table 5C: Per-seed out-of-sample comparison on deduplicated `ext8` (`[30, 34, 37, 42, 45, 48, 57, 58]`)

| Seed | Source | OC carbon raw / luck-adj. (`day`, `P`) | Solver raw / luck-adj. (`day`, `P`) | Heuristic raw / luck-adj. (`day`, `P`) |
|---:|---|---|---|---|
| 30 | `fleet_replication` | `+0.540` / `+0.400` (`d11`, `0.909`) | `-1.000` / `+0.175` (`d18`, `0.858`) | `+0.160` / `-0.421` (`d19`, `0.499`) |
| 34 | `committed_g1` | `+0.790` / `+0.752` (`d5`, `0.979`) | `+0.700` / `+0.663` (`d6`, `0.978`) | `+0.310` / `+0.244` (`d15`, `0.950`) |
| 37 | `committed_g1` | `+0.700` / `+0.668` (`d6`, `0.981`) | `+0.770` / `+0.635` (`d5`, `0.924`) | `+0.320` / `+0.284` (`d19`, `0.973`) |
| 42 | `fleet_replication` | `+0.570` / `+0.521` (`d12`, `0.969`) | `+0.510` / `+0.505` (`d10`, `0.997`) | `+0.090` / `+0.087` (`d18`, `0.997`) |
| 45 | `fleet_replication` | `+0.590` / `+0.547` (`d16`, `0.973`) | `+0.490` / `+0.423` (`d11`, `0.955`) | `-1.000` / `-0.988` (`d19`, `0.011`) |
| 48 | `fleet_replication` | `+0.610` / `+0.475` (`d13`, `0.916`) | `+0.460` / `+0.394` (`d9`, `0.955`) | `+0.320` / `+0.254` (`d15`, `0.950`) |
| 57 | `fleet_replication` | `+0.760` / `+0.707` (`d8`, `0.970`) | `+0.540` / `+0.384` (`d8`, `0.899`) | `+0.270` / `+0.206` (`d16`, `0.950`) |
| 58 | `fleet_replication` | `+0.580` / `+0.435` (`d11`, `0.908`) | `+0.530` / `+0.441` (`d9`, `0.942`) | `+0.490` / `+0.344` (`d10`, `0.902`) |

On all `8` completed out-of-sample extension seeds (`ext8`), `opencode:google/gemini-4-carbon` sweeps `heuristic` **`8-0-0`** both raw (`+0.522` V/seed) and luck-adjusted (`+0.562` V/seed, `p = 0.0078`), and leads `solver` `7-0-1` on those `8` seeds (`+0.110` luck-adjusted). Pooled across all `38` observed seeds (`pooled38`), `gemini-4-carbon` beats `heuristic` **`32-0-6`** luck-adjusted (`+0.361 +/- 0.156`) while remaining below the reference `solver` at **`82.2%` `[64%, 100%]`** luck-adjusted (`17-0-21` W-T-L); the primary `0-29` headline remains **`65%`** raw / **`72%`** luck-adjusted.

## 6. Keyless Reproduction Commands

```bash
CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/analyze_v14_harness_and_family_gap.py --check
CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/analyze_v14_harness_and_family_gap.py --json
CANARY_ALLOW_DEV=1 PYTHONPATH=. pytest -q tests/test_v14_harness_and_ext_synthesis.py
```
