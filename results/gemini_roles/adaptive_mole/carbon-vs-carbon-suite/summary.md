# Role 2 Consolidated Suite: Adaptive Gemini Mole (`gemini-4-carbon`)

- Role: `adaptive_mole`
- Target Model ID: `gemini-4-carbon`
- Verified `adaptive_mole` run folders consolidated: `18`
- Total Gemini API calls: `1038`
- Total tokens (in / out / thinking / cached): `8,968,009` / `80,898` / `198,438` / `7,462,380`
- Total estimated cost (USD): `$6.550866`
- Provenance note: `carbon-vs-carbon-suite/` intentionally omits `meta.json` so `canary.gemini.provenance` does not double-count tokens or costs.

## 1. Head-to-Head Carbon-vs-Carbon Clash Suite (`clash_suite`)

| Slice | Shards | Episodes | Investigator Acc | Investigator Mean | Solver Acc | Solver Mean | Solvable Rate | Mean Regret | Mole Leaks | Mole Frames | Mole Errors | Combined Tokens (in/out/think) | Inv Cost | Mole Cost | Total Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| `medium` | 5 | 10 | 100.00% | +0.6760 | 80.00% | +0.3140 | 80.00% | -0.3620 | 33 | 12 | 0 | `8,427,169/18,570/147,888` | $3.9437 | $0.3967 | $4.3404 |
| `hard` | 0 | 0 | 0.00% | +0.0000 | 0.00% | +0.0000 | 0.00% | +0.0000 | 0 | 0 | 0 | `0/0/0` | $0.0000 | $0.0000 | $0.0000 |
| `overall` | 5 | 10 | 100.00% | +0.6760 | 80.00% | +0.3140 | 80.00% | -0.3620 | 33 | 12 | 0 | `8,427,169/18,570/147,888` | $3.9437 | $0.3967 | $4.3404 |

### Per-Seed Clash Shards

| Run Folder | Tier | Seed | Commit | Inv Score | Inv Correct | Solver Score | Solver Correct | Solvable | Regret | Leaks | Frames | Errors | Cost (USD) |
| --- | --- | ---: | --- | ---: | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-seed0` | `medium` | 0 | `3bd1d1e229` | +0.6600 | True | +0.4000 | True | True | -0.2600 | 7 | 1 | 0 | $0.8882 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed1` | `medium` | 1 | `9222669912` | +0.7300 | True | +0.3300 | True | True | -0.4000 | 6 | 2 | 0 | $0.6835 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed2` | `medium` | 2 | `9222669912` | +0.6800 | True | +0.0000 | False | False | -0.6800 | 6 | 3 | 0 | $1.0267 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed3` | `medium` | 3 | `797cc1d249` | +0.5600 | True | +0.3900 | True | True | -0.1700 | 9 | 4 | 0 | $1.0813 |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-med-seed5` | `medium` | 5 | `9222669912` | +0.7500 | True | +0.4500 | True | True | -0.3000 | 5 | 2 | 0 | $0.6607 |

## 2. Live Arena Adaptive Mole Suite (`live_arena_suite`)

| Slice | Investigator | Adaptive Mole Mean | Adaptive Mole Acc | Default Mole Mean | Default Mole Acc | Delta Mean (Adaptive - Default) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `medium` (n=6) | `solver` | +0.2833 | 50.00% | +0.5967 | 83.33% | -0.3134 |
| `medium` (n=6) | `grok_tactics` | +0.0000 | 0.00% | +0.4417 | 83.33% | -0.4417 |
| `medium` (n=6) | `obvious_heuristic` | -1.0000 | 0.00% | -1.0000 | 0.00% | +0.0000 |
| `hard` (n=12) | `solver` | +0.5575 | 91.67% | +0.5758 | 91.67% | -0.0183 |
| `hard` (n=12) | `grok_tactics` | +0.0000 | 0.00% | +0.4592 | 91.67% | -0.4592 |
| `hard` (n=12) | `obvious_heuristic` | -0.8467 | 8.33% | -1.0000 | 0.00% | +0.1533 |
| `overall` (n=18) | `solver` | +0.4661 | 77.78% | +0.5828 | 88.89% | -0.1167 |
| `overall` (n=18) | `grok_tactics` | +0.0000 | 0.00% | +0.4533 | 88.89% | -0.4533 |
| `overall` (n=18) | `obvious_heuristic` | -0.8978 | 5.56% | -1.0000 | 0.00% | +0.1022 |

### Live Arena Seed Batches

| Run Folder | Tier | Seeds | Commit | Decisions | Leaks | Frames | LLM Errors | Solvable | Calls | Tokens (in/out/think) | Cost (USD) |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-med012` | `medium` | `[0, 1, 2]` | `d39e88c39e` | 77 | 59 | 77 | 0 | True | 77 | `61,299/4,959/5,588` | $0.2281 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-med345` | `medium` | `[3, 4, 5]` | `c00d49189d` | 86 | 77 | 86 | 0 | True | 86 | `71,969/5,638/6,358` | $0.2639 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-hard012` | `hard` | `[0, 1, 2]` | `03c676c1d3` | 97 | 86 | 97 | 0 | True | 97 | `86,618/6,331/6,287` | $0.2994 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-hard345` | `hard` | `[3, 4, 5]` | `c00d49189d` | 106 | 88 | 106 | 0 | True | 106 | `92,992/6,876/6,671` | $0.3215 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-hard678` | `hard` | `[6, 7, 8]` | `c00d49189d` | 85 | 82 | 85 | 0 | True | 85 | `79,191/5,702/5,306` | $0.2685 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-hard9_10_11` | `hard` | `[9, 10, 11]` | `6620fad9ee` | 88 | 68 | 88 | 0 | True | 88 | `76,544/5,664/5,643` | $0.2662 |

## 3. Mole Forge Evolutionary DSL Suite (`mole_forge_suite`)

| Run Folder | Tier | Gens | Valid LLM Children | Best Fitness | Default Dev Fitness | Fresh Solver Acc | Fresh Min Regret | Default Fresh Min Regret | Calls | Cost (USD) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `results/gemini_roles/adaptive_mole/mole-forge-carbon-hard-deep` | `hard` | 8 | 49 | 0.3745 | 0.0560 | 90.00% | 0.2310 | 0.1650 | 8 | $0.2042 |
| `results/gemini_roles/adaptive_mole/mole-forge-carbon-v14` | `hard` | 3 | 6 | 0.3700 | 0.2450 | 95.00% | 0.2395 | 0.2420 | 12 | $0.0275 |

## 4. PAIRED Solvable Scenario Designer Suite (`paired_designer_suite`)

| Run Folder | Tier | Subrole | Kept / Valid | Design/Kept Solver Mean | Design/Kept Heuristic Mean | Holdout Full Solver Mean | Holdout Heuristic Mean | Top Scenario | Calls | Cost (USD) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `results/gemini_roles/adaptive_mole/paired-designer-carbon` | `medium` | `paired_designer` | 3/4 | +0.5743 | -1.0000 | n/a | n/a | - | 1 | $0.0218 |
| `results/gemini_roles/adaptive_mole/paired-solvable-scenarios-carbon` | `medium` | `paired_skill_designer` | 3/4 | +0.7100 | -1.0000 | +0.7220 | -0.8110 | `high_tempo_frame_rotator` | 1 | $0.0176 |
| `results/gemini_roles/adaptive_mole/paired-designer-carbon-hard` | `hard` | `paired_designer` | 6/6 | +0.6827 | -1.0000 | n/a | n/a | - | 1 | $0.0271 |
| `results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-hard` | `hard` | `paired_skill_designer` | 6/6 | +0.6890 | -1.0000 | +0.6280 | -1.0000 | `rotating_blame_sprinter` | 1 | $0.0233 |

## Additional Verified Adaptive Mole Runs

| Run Folder | Subrole | Commit | Calls | Tokens (in/out/think) | Cost (USD) |
| --- | --- | --- | ---: | --- | ---: |
| `results/gemini_roles/adaptive_mole/catchability-audit-carbon` | `catchability_isolation_audit` | `61575b33eb` | 7 | `50,469/7,872/6,194` | $0.2416 |

## 5. De-Duplicated Role 2 Totals (`totals`)

| Suite Slice | Verified Folders | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `clash_suite` | 5 | 468 | 8,427,169 | 18,570 | 147,888 | 7,462,380 | $4.340406 |
| `live_arena_suite` | 6 | 539 | 468,613 | 35,170 | 35,853 | 0 | $1.647456 |
| `mole_forge_suite` | 2 | 20 | 14,679 | 14,091 | 6,138 | 0 | $0.231648 |
| `paired_designer_suite` | 4 | 4 | 7,079 | 5,195 | 2,365 | 0 | $0.089758 |
| `other_verified_runs` | 1 | 7 | 50,469 | 7,872 | 6,194 | 0 | $0.241598 |
| **total** | **18** | **1038** | **8,968,009** | **80,898** | **198,438** | **7,462,380** | **$6.550866** |
