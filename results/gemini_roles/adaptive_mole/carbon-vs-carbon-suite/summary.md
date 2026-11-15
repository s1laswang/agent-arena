# Role 2 Consolidated Suite: Adaptive Gemini Mole (`gemini-4-carbon`)

- Role: `adaptive_mole`
- Target Model ID: `gemini-4-carbon`
- Verified `adaptive_mole` run folders consolidated: `28`
- Total Gemini API calls: `1763`
- Total tokens (in / out / thinking / cached): `28,044,684` / `123,907` / `443,644` / `25,213,697`
- Total estimated cost (USD): `$13.858871`
- Provenance note: `carbon-vs-carbon-suite/` intentionally omits `meta.json` so `canary.gemini.provenance` does not double-count tokens or costs.

## 1. Head-to-Head Carbon-vs-Carbon Clash Suite (`clash_suite`)

| Slice | Shards | Episodes | Investigator Acc (95% CI) | Investigator Mean (95% CI) | Solver Acc | Solver Mean (95% CI) | Solvable Rate (95% CI) | Mean Regret (95% CI) | Mole Leaks | Mole Frames | Mole Errors | Combined Tokens (in/out/think) | Inv Cost | Mole Cost | Total Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| `medium` | 6 | 12 | 100.00% [61.0%, 100.0%] | +0.6967 [+0.6333, +0.7533] | 66.67% | +0.2617 [+0.1100, +0.4050] | 66.67% [30.0%, 90.3%] | -0.4350 [-0.6233, -0.2600] | 37 | 13 | 0 | `9,274,985/21,212/173,745` | $4.4955 | $0.4735 | $4.9690 |
| `hard` | 4 | 8 | 100.00% [51.0%, 100.0%] | +0.4075 [+0.1250, +0.6025] | 75.00% | +0.4600 [+0.1775, +0.7250] | 75.00% [30.1%, 95.4%] | +0.0525 [-0.0650, +0.1875] | 41 | 9 | 0 | `18,089,578/20,763/202,081` | $5.6611 | $0.3710 | $6.0321 |
| `overall` | 10 | 20 | 100.00% [72.2%, 100.0%] | +0.5810 [+0.4340, +0.6920] | 70.00% | +0.3410 [+0.1840, +0.5050] | 70.00% [39.7%, 89.2%] | -0.2400 [-0.4350, -0.0500] | 78 | 22 | 0 | `27,364,563/41,975/375,826` | $10.1566 | $0.8445 | $11.0011 |

### Per-Seed Clash Shards

| Run Folder | Tier | Seed | Commit | Inv Score | Inv Correct | Solver Score | Solver Correct | Solvable | Regret | Leaks | Frames | Errors | Cost (USD) |
| --- | --- | ---: | --- | ---: | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-seed0` | `medium` | 0 | `3bd1d1e229` | +0.6600 | True | +0.4000 | True | True | -0.2600 | 7 | 1 | 0 | $0.8882 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed1` | `medium` | 1 | `9222669912` | +0.7300 | True | +0.3300 | True | True | -0.4000 | 6 | 2 | 0 | $0.6835 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed2` | `medium` | 2 | `9222669912` | +0.6800 | True | +0.0000 | False | False | -0.6800 | 6 | 3 | 0 | $1.0267 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed3` | `medium` | 3 | `797cc1d249` | +0.5600 | True | +0.3900 | True | True | -0.1700 | 9 | 4 | 0 | $1.0813 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed4` | `medium` | 4 | `8425507a27` | +0.8000 | True | +0.0000 | False | False | -0.8000 | 4 | 1 | 0 | $0.6286 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed5` | `medium` | 5 | `9222669912` | +0.7500 | True | +0.4500 | True | True | -0.3000 | 5 | 2 | 0 | $0.6607 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-hard-seed0` | `hard` | 0 | `e650291e78` | +0.6400 | True | +0.7100 | True | True | +0.0700 | 6 | 1 | 0 | $0.8087 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-hard-seed1` | `hard` | 1 | `b73b62ffec` | +0.0000 | True | +0.0000 | False | False | +0.0000 | 17 | 5 | 0 | $2.6374 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-hard-seed2` | `hard` | 2 | `38cd16ece1` | +0.5000 | True | +0.3900 | True | True | -0.1100 | 9 | 1 | 0 | $1.1844 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-hard-seed3` | `hard` | 3 | `db9a94b0be` | +0.4900 | True | +0.7400 | True | True | +0.2500 | 9 | 2 | 0 | $1.4017 |

## 2. Live Arena Adaptive Mole Suite (`live_arena_suite`)

| Slice | Investigator | Adaptive Mole Mean (95% CI) | Adaptive Mole Acc (95% CI) | Default Mole Mean (95% CI) | Default Mole Acc | Paired Delta Mean (95% CI) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `medium` (n=12) | `solver` | +0.4075 [+0.2608, +0.5417] | 75.00% [46.8%, 91.1%] | +0.6258 [+0.4942, +0.7200] | 91.67% | -0.2183 [-0.4058, -0.0375] |
| `medium` (n=12) | `grok_tactics` | +0.0000 [+0.0000, +0.0000] | 0.00% [0.0%, 24.2%] | +0.5283 [+0.3717, +0.6908] | 83.33% | -0.5283 [-0.6908, -0.3717] |
| `medium` (n=12) | `obvious_heuristic` | -1.0000 [-1.0000, -1.0000] | 0.00% [0.0%, 24.2%] | -1.0000 [-1.0000, -1.0000] | 0.00% | +0.0000 [+0.0000, +0.0000] |
| `hard` (n=12) | `solver` | +0.5575 [+0.4308, +0.6642] | 91.67% [64.6%, 98.5%] | +0.5758 [+0.4517, +0.6650] | 91.67% | -0.0183 [-0.1800, +0.1592] |
| `hard` (n=12) | `grok_tactics` | +0.0000 [+0.0000, +0.0000] | 0.00% [0.0%, 24.2%] | +0.4592 [+0.3275, +0.5858] | 91.67% | -0.4592 [-0.5867, -0.3283] |
| `hard` (n=12) | `obvious_heuristic` | -0.8467 [-1.0000, -0.5400] | 8.33% [1.5%, 35.4%] | -1.0000 [-1.0000, -1.0000] | 0.00% | +0.1533 [+0.0000, +0.4600] |
| `overall` (n=24) | `solver` | +0.4825 [+0.3754, +0.5767] | 83.33% [64.1%, 93.3%] | +0.6008 [+0.5146, +0.6729] | 91.67% | -0.1183 [-0.2517, +0.0142] |
| `overall` (n=24) | `grok_tactics` | +0.0000 [+0.0000, +0.0000] | 0.00% [0.0%, 13.8%] | +0.4937 [+0.3879, +0.5863] | 87.50% | -0.4937 [-0.5867, -0.3887] |
| `overall` (n=24) | `obvious_heuristic` | -0.9233 [-1.0000, -0.7700] | 4.17% [0.7%, 20.2%] | -1.0000 [-1.0000, -1.0000] | 0.00% | +0.0767 [+0.0000, +0.2300] |

### Live Arena Seed Batches

| Run Folder | Tier | Seeds | Commit | Decisions | Leaks | Frames | LLM Errors | Solvable | Calls | Tokens (in/out/think) | Cost (USD) |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-med012` | `medium` | `[0, 1, 2]` | `d39e88c39e` | 77 | 59 | 77 | 0 | True | 77 | `61,299/4,959/5,588` | $0.2281 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-med345` | `medium` | `[3, 4, 5]` | `c00d49189d` | 86 | 77 | 86 | 0 | True | 86 | `71,969/5,638/6,358` | $0.2639 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-med678` | `medium` | `[6, 7, 8]` | `8425507a27` | 79 | 67 | 79 | 0 | True | 79 | `63,938/5,151/5,915` | $0.2385 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-med9_10_11` | `medium` | `[9, 10, 11]` | `5fd627a7b1` | 78 | 66 | 78 | 0 | True | 78 | `62,793/4,996/5,766` | $0.2332 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-hard012` | `hard` | `[0, 1, 2]` | `03c676c1d3` | 97 | 86 | 97 | 0 | True | 97 | `86,618/6,331/6,287` | $0.2994 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-hard345` | `hard` | `[3, 4, 5]` | `c00d49189d` | 106 | 88 | 106 | 0 | True | 106 | `92,992/6,876/6,671` | $0.3215 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-hard678` | `hard` | `[6, 7, 8]` | `c00d49189d` | 85 | 82 | 85 | 0 | True | 85 | `79,191/5,702/5,306` | $0.2685 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-hard9_10_11` | `hard` | `[9, 10, 11]` | `6620fad9ee` | 88 | 68 | 88 | 0 | True | 88 | `76,544/5,664/5,643` | $0.2662 |

## 3. Mole Forge Evolutionary DSL Suite (`mole_forge_suite`)

| Run Folder | Tier | Gens | Valid LLM Children | Best Fitness | Default Dev Fitness | Fresh Solver Acc | Fresh Min Regret | Default Fresh Min Regret | Confirm Holdout Acc | Calls | Cost (USD) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `results/gemini_roles/adaptive_mole/mole-forge-carbon-med-deep` | `medium` | 8 | 43 | 0.7381 | 0.6315 | 85.00% | 0.1390 | 0.1610 | 90.00% (n=40) | 19 | $0.1288 |
| `results/gemini_roles/adaptive_mole/mole-forge-carbon-hard-deep` | `hard` | 8 | 49 | 0.3745 | 0.0560 | 90.00% | 0.2310 | 0.1650 | 85.00% (n=20) | 8 | $0.2042 |
| `results/gemini_roles/adaptive_mole/mole-forge-carbon-v14` | `hard` | 3 | 6 | 0.3700 | 0.2450 | 95.00% | 0.2395 | 0.2420 | n/a | 12 | $0.0275 |

## 4. PAIRED Solvable Scenario Designer Suite (`paired_designer_suite`)

| Run Folder | Tier | Subrole | Kept / Valid | Design/Kept Solver Mean | Design/Kept Heuristic Mean | Holdout Full Solver Mean | Holdout Heuristic Mean | Top Scenario | Calls | Cost (USD) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `results/gemini_roles/adaptive_mole/paired-designer-carbon` | `medium` | `paired_designer` | 3/4 | +0.5743 | -1.0000 | n/a | n/a | - | 1 | $0.0218 |
| `results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-med-s10_14` | `medium` | `paired_skill_designer` | 6/6 | +0.6888 | -1.0000 | +0.5921 | -1.0000 | `paced_cadence_framer` | 1 | $0.0235 |
| `results/gemini_roles/adaptive_mole/paired-solvable-scenarios-carbon` | `medium` | `paired_skill_designer` | 3/4 | +0.7100 | -1.0000 | +0.7220 | -0.8110 | `high_tempo_frame_rotator` | 1 | $0.0176 |
| `results/gemini_roles/adaptive_mole/paired-designer-carbon-hard` | `hard` | `paired_designer` | 6/6 | +0.6827 | -1.0000 | n/a | n/a | - | 1 | $0.0271 |
| `results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-hard` | `hard` | `paired_skill_designer` | 6/6 | +0.6890 | -1.0000 | +0.6280 | -1.0000 | `rotating_blame_sprinter` | 1 | $0.0233 |
| `results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-hard-s10_14` | `hard` | `paired_skill_designer` | 5/6 | +0.6280 | -1.0000 | +0.4970 | -1.0000 | `adaptive_heat_deflector` | 1 | $0.0232 |

## Catchability & Secret-Isolation Audit (`catchability_audit`)

- Audit folder: `results/gemini_roles/adaptive_mole/catchability-audit-carbon` (commit `61575b33eb`)
- Runs / strategies / live decisions / MoleViews checked: `14` / `42` / `573` / `8783`
- Privileged-state isolation violations: `0` (file secret leaks: `0`)
- Catchability compliance: `45/50` (`90.00%` [78.6%, 95.7%])
- Zero privileged canary awareness confirmed by `gemini-4-carbon`: `True`

## Additional Verified Adaptive Mole Runs

| Run Folder | Subrole | Commit | Calls | Tokens (in/out/think) | Cost (USD) |
| --- | --- | --- | ---: | --- | ---: |
| `results/gemini_roles/adaptive_mole/catchability-audit-carbon` | `catchability_isolation_audit` | `61575b33eb` | 7 | `50,469/7,872/6,194` | $0.2416 |

## 5. De-Duplicated Role 2 Totals (`totals`)

| Suite Slice | Verified Folders | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `clash_suite` | 10 | 1015 | 27,364,563 | 41,975 | 375,826 | 25,213,697 | $11.001129 |
| `live_arena_suite` | 8 | 696 | 595,344 | 45,317 | 47,534 | 0 | $2.119198 |
| `mole_forge_suite` | 3 | 39 | 23,935 | 20,771 | 10,491 | 0 | $0.360490 |
| `paired_designer_suite` | 6 | 6 | 10,373 | 7,972 | 3,599 | 0 | $0.136456 |
| `other_verified_runs` | 1 | 7 | 50,469 | 7,872 | 6,194 | 0 | $0.241598 |
| **total** | **28** | **1763** | **28,044,684** | **123,907** | **443,644** | **25,213,697** | **$13.858871** |
