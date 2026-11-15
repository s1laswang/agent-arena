# Role 3 Consolidated Suite: Frontier Investigators Paired vs SolverPolicy (`gemini-4-carbon`)

- Role: `investigators`
- Target Model ID: `gemini-4-carbon` (`tiers_version=v1.4`)
- Verified run folders: `28` (`25` frontier + `2` thinking-ladder + `1` hint-ablation)
- Replay-verified episodes: `41 / 41` (`33` unique frontier episodes)
- Transcript thought-signature audit: `41` transcripts verified, `3560` redacted signature parts, `0` raw base64 leaks
- Total Gemini API calls: `3,565`
- Total tokens (in / out / thinking / cached): `129,967,004` / `1,502,416` / `157,797` / `120,952,167`
- Total cost (USD, cache-adjusted est / uncached list): `$46.7270` / `$276.5361`
- Hygiene & secret scan violations: `0`

## 1. In-Process `gemini-4-carbon` Investigator Paired vs `SolverPolicy` (v1.4)

| Slice | Seeds (n) | Carbon Mean +/- 95% CI | Carbon Acc (95% CI) | Mean Accuse Day | Mean P(accused) | Solver Mean | Carbon / Solver (95% Boot CI) | Paired Diff +/- 95% CI | Luck-Adj Carbon / Solver (95% Boot CI) |
| --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- | --- |
| `easy` | 4 | +0.850 +/- 0.035 | 100.0% [51.0%, 100.0%] | 3.8 | 1.000 | +0.800 | 106.2% [100.0%, 113.2%] | +0.050 +/- 0.061 | 112.3% [100.0%, 135.5%] |
| `medium` | 11 | +0.594 +/- 0.180 | 81.8% [52.3%, 94.9%] | 8.8 | 1.000 | +0.740 | 80.2% [52.6%, 106.2%] | -0.146 +/- 0.211 | 80.2% [52.6%, 106.2%] |
| `hard` | 18 | +0.506 +/- 0.181 | 94.4% [74.2%, 99.0%] | 11.2 | 0.931 | +0.533 | 94.8% [53.7%, 130.2%] | -0.028 +/- 0.213 | 99.4% [84.5%, 119.4%] |
| `medium_plus_hard` | 29 | +0.539 +/- 0.130 | 89.7% [73.6%, 96.4%] | 10.4 | 0.954 | +0.612 | 88.1% [62.7%, 110.8%] | -0.073 +/- 0.154 | 90.2% [74.7%, 106.2%] |
| `all_tiers` | 33 | +0.577 +/- 0.120 | 90.9% [76.4%, 96.9%] | 9.5 | 0.960 | +0.635 | 90.9% [69.1%, 110.4%] | -0.058 +/- 0.136 | 93.5% [79.5%, 107.7%] |

## 2. Thinking-Level Ablation (`low` vs `high`) Paired vs `SolverPolicy`

| Run Folder | Level | Tier | n | Mean Score | Acc | Accuse Day | P(accused) | Solver Mean | Paired Diff | Regret / Ep |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `thinking-ladder-carbon-hard0` | `high` | `hard` | 1 | +0.360 | 100.0% | 13.0 | 0.998 | +0.640 | -0.280 | 0.0298 |
| `thinking-ladder-carbon-hard0` | `low` | `hard` | 1 | +0.780 | 100.0% | 7.0 | 0.951 | +0.640 | +0.140 | 0.1623 |
| `thinking-ladder-carbon-med01` | `high` | `medium` | 2 | +0.655 | 100.0% | 9.5 | 1.000 | +0.565 | +0.090 | 0.0279 |
| `thinking-ladder-carbon-med01` | `low` | `medium` | 2 | +0.655 | 100.0% | 10.0 | 1.000 | +0.565 | +0.090 | 0.0461 |

## 3. Failure-Mode Hint Ablation Paired vs Unhinted `gemini-4-carbon` and `SolverPolicy`

| Run Folder | Hint Tags | n | Hinted Mean | Unhinted Mean | Delta vs Unhinted | Solver Mean | Hinted Regret / Ep | Unhinted Regret / Ep |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `hint-ablation-carbon-med01` | `premature_accusation,ignored_delay` | 2 | +0.630 | +0.700 | -0.070 | +0.565 | 0.0176 | 0.0359 |

## 4. Verified Run Folders Inventory (`results/gemini/roles_carbon/investigators/`)

| Run Folder | Subrole | Episodes | Calls | Tokens In | Tokens Out | Thinking | Cached | Est Cost (USD) | Verified |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `easy-0-3` | `frontier_investigator` | 4 | 133 | 1,557,467 | 50,927 | 0 | 1,235,555 | $1.2767 | yes |
| `hard-0` | `frontier_investigator` | 1 | 112 | 4,362,422 | 44,812 | 0 | 4,090,963 | $1.4001 | yes |
| `hard-1` | `frontier_investigator` | 1 | 117 | 4,296,964 | 48,641 | 0 | 3,971,769 | $1.5340 | yes |
| `hard-10` | `frontier_investigator` | 1 | 106 | 5,105,883 | 52,484 | 0 | 4,839,236 | $1.5421 | yes |
| `hard-11` | `frontier_investigator` | 1 | 48 | 1,451,142 | 39,530 | 0 | 1,320,404 | $0.7888 | yes |
| `hard-12` | `frontier_investigator` | 1 | 102 | 3,352,345 | 40,012 | 0 | 3,106,048 | $1.2033 | yes |
| `hard-13` | `frontier_investigator` | 1 | 116 | 6,496,251 | 70,774 | 0 | 6,191,082 | $1.9372 | yes |
| `hard-14` | `frontier_investigator` | 1 | 63 | 1,907,302 | 33,589 | 0 | 1,744,958 | $0.8351 | yes |
| `hard-17` | `frontier_investigator` | 1 | 82 | 2,363,734 | 36,628 | 0 | 2,163,578 | $0.9829 | yes |
| `hard-18` | `frontier_investigator` | 1 | 74 | 2,888,736 | 43,465 | 0 | 2,692,520 | $1.0963 | yes |
| `hard-19` | `frontier_investigator` | 1 | 152 | 9,794,174 | 80,044 | 0 | 9,405,740 | $2.5179 | yes |
| `hard-2` | `frontier_investigator` | 1 | 76 | 2,018,060 | 30,619 | 0 | 1,796,222 | $0.9295 | yes |
| `hard-3` | `frontier_investigator` | 1 | 128 | 6,813,652 | 66,707 | 0 | 6,448,448 | $2.0423 | yes |
| `hard-4` | `frontier_investigator` | 1 | 150 | 7,623,574 | 66,088 | 0 | 7,262,745 | $2.1088 | yes |
| `hard-5` | `frontier_investigator` | 1 | 67 | 2,500,684 | 47,823 | 0 | 2,263,660 | $1.1786 | yes |
| `hard-6` | `frontier_investigator` | 1 | 57 | 2,144,797 | 51,865 | 0 | 1,985,523 | $1.0357 | yes |
| `hard-7` | `frontier_investigator` | 1 | 117 | 5,726,242 | 69,668 | 0 | 5,437,640 | $1.8176 | yes |
| `hard-8` | `frontier_investigator` | 1 | 96 | 3,557,523 | 46,233 | 0 | 3,283,687 | $1.3384 | yes |
| `hard-9` | `frontier_investigator` | 1 | 73 | 2,797,383 | 47,577 | 0 | 2,603,465 | $1.1240 | yes |
| `hint-ablation-carbon-med01` | `hint_ablation` | 2 | 173 | 4,829,333 | 70,201 | 0 | 4,413,503 | $1.9750 | yes |
| `medium-0-1` | `frontier_investigator` | 2 | 163 | 4,658,670 | 71,772 | 0 | 4,257,294 | $1.9462 | yes |
| `medium-11` | `frontier_investigator` | 1 | 67 | 2,160,182 | 40,249 | 0 | 1,987,383 | $0.9468 | yes |
| `medium-2-3` | `frontier_investigator` | 2 | 125 | 2,625,822 | 58,964 | 0 | 2,314,808 | $1.4431 | yes |
| `medium-4-5` | `frontier_investigator` | 2 | 278 | 9,686,117 | 95,196 | 0 | 9,032,227 | $3.1630 | yes |
| `medium-6-7` | `frontier_investigator` | 2 | 218 | 7,742,118 | 98,798 | 0 | 7,222,312 | $2.7498 | yes |
| `medium-8-9` | `frontier_investigator` | 2 | 191 | 5,767,066 | 83,656 | 0 | 5,308,215 | $2.2851 | yes |
| `thinking-ladder-carbon-hard0` | `hard_thinking_ablation` | 2 | 163 | 6,499,263 | 5,422 | 52,968 | 6,101,700 | $1.9892 | yes |
| `thinking-ladder-carbon-med01` | `thinking_level_ablation` | 4 | 318 | 9,240,098 | 10,672 | 104,829 | 8,471,482 | $3.5394 | yes |
