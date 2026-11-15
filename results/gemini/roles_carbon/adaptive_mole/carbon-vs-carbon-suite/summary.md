# Consolidated Suite: Adaptive Gemini Mole (`gemini-4-carbon`)

- Role: `adaptive_mole`
- Environment scope: `arena mode, not the judged v1.4 environment`
- Target Model ID: `gemini-4-carbon`
- Verified `adaptive_mole` run folders consolidated: `30`
- Total Gemini API calls: `1554`
- Total tokens (in / out / thinking / cached): `36,387,758` / `98,901` / `587,486` / `33,025,731`
- Total estimated cost (USD): `$16.890513`
- Provenance note: `carbon-vs-carbon-suite/` omits `meta.json` so role scanners do not double-count tokens or costs.

## 1. Head-to-Head Carbon-vs-Carbon Clash Suite (`clash_suite`)

| Slice | Shards | Episodes | Investigator Acc (95% CI) | Investigator Mean (95% CI) | Solver Acc | Solver Mean (95% CI) | Solvable Rate (95% CI) | Mean Regret (95% CI) | Mole Leaks | Mole Frames | Mole Errors | Combined Tokens (in/out/think) | Inv Cost | Mole Cost | Total Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| `easy` | 1 | 2 | 100.00% [20.6%, 100.0%] | +0.8300 [+0.8300, +0.8300] | 100.00% | +0.7900 [+0.7900, +0.7900] | 100.00% [20.6%, 100.0%] | -0.0400 [-0.0400, -0.0400] | 3 | 1 | 0 | `366,514/1,734/17,294` | $0.3630 | $0.0458 | $0.4088 |
| `medium` | 10 | 20 | 100.00% [72.2%, 100.0%] | +0.7070 [+0.6600, +0.7490] | 80.00% | +0.3700 [+0.2290, +0.5130] | 80.00% [49.0%, 94.3%] | -0.3370 [-0.4900, -0.1910] | 59 | 18 | 0 | `15,641,751/34,250/308,756` | $8.0420 | $0.7564 | $8.7984 |
| `hard` | 5 | 10 | 100.00% [56.5%, 100.0%] | +0.4280 [+0.2020, +0.5840] | 80.00% | +0.4880 [+0.2260, +0.7000] | 80.00% [37.5%, 96.4%] | +0.0600 [-0.0440, +0.1680] | 50 | 13 | 0 | `20,333,111/24,138/242,284` | $6.5612 | $0.4500 | $7.0112 |
| `overall` | 16 | 32 | 100.00% [80.6%, 100.0%] | +0.6275 [+0.5256, +0.7075] | 81.25% | +0.4331 [+0.3088, +0.5569] | 81.25% [57.0%, 93.4%] | -0.1944 [-0.3369, -0.0625] | 112 | 32 | 0 | `36,341,376/60,122/568,334` | $14.9663 | $1.2522 | $16.2184 |

### Per-Seed Clash Shards

| Run Folder | Tier | Seed | Commit | Inv Score | Inv Correct | Solver Score | Solver Correct | Solvable | Regret | Leaks | Frames | Errors | Cost (USD) |
| --- | --- | ---: | --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-easy-seed0` | `easy` | 0 | `cec07dc8ea` | +0.8300 | True | +0.7900 | True | True | -0.0400 | 3 | 1 | 0 | $0.4088 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-seed0` | `medium` | 0 | `3bd1d1e229` | +0.6600 | True | +0.4000 | True | True | -0.2600 | 7 | 1 | 0 | $0.8882 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-med-seed1` | `medium` | 1 | `9222669912` | +0.7300 | True | +0.3300 | True | True | -0.4000 | 6 | 2 | 0 | $0.6835 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-med-seed2` | `medium` | 2 | `9222669912` | +0.6800 | True | +0.0000 | False | False | -0.6800 | 6 | 3 | 0 | $1.0267 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-med-seed3` | `medium` | 3 | `797cc1d249` | +0.5600 | True | +0.3900 | True | True | -0.1700 | 9 | 4 | 0 | $1.0813 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-med-seed4` | `medium` | 4 | `8425507a27` | +0.8000 | True | +0.0000 | False | False | -0.8000 | 4 | 1 | 0 | $0.6286 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-med-seed5` | `medium` | 5 | `9222669912` | +0.7500 | True | +0.4500 | True | True | -0.3000 | 5 | 2 | 0 | $0.6607 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-med-seed6` | `medium` | 6 | `8425507a27` | +0.7500 | True | +0.3400 | True | True | -0.4100 | 5 | 1 | 0 | $0.7479 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-med-seed7` | `medium` | 7 | `cec07dc8ea` | +0.7000 | True | +0.3500 | True | True | -0.3500 | 6 | 2 | 0 | $0.7888 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-med-seed8` | `medium` | 8 | `632b258f19` | +0.8000 | True | +0.7300 | True | True | -0.0700 | 4 | 2 | 0 | $0.9581 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-med-seed9` | `medium` | 9 | `632b258f19` | +0.6400 | True | +0.7100 | True | True | +0.0700 | 7 | 0 | 0 | $1.3346 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-hard-seed0` | `hard` | 0 | `e650291e78` | +0.6400 | True | +0.7100 | True | True | +0.0700 | 6 | 1 | 0 | $0.8087 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-hard-seed1` | `hard` | 1 | `b73b62ffec` | +0.0000 | True | +0.0000 | False | False | +0.0000 | 17 | 5 | 0 | $2.6374 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-hard-seed2` | `hard` | 2 | `38cd16ece1` | +0.5000 | True | +0.3900 | True | True | -0.1100 | 9 | 1 | 0 | $1.1844 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-hard-seed3` | `hard` | 3 | `db9a94b0be` | +0.4900 | True | +0.7400 | True | True | +0.2500 | 9 | 2 | 0 | $1.4017 |
| `results/gemini/roles_carbon/adaptive_mole/carbon-vs-carbon-hard-seed4` | `hard` | 4 | `d5fee698c7` | +0.5100 | True | +0.6000 | True | True | +0.0900 | 9 | 4 | 0 | $0.9791 |

## 2. Live Arena Adaptive Mole Suite (`live_arena_suite`)

| Slice | Investigator | Adaptive Mole Mean (95% CI) | Adaptive Mole Acc (95% CI) | Default Mole Mean (95% CI) | Default Mole Acc | Paired Delta Mean (95% CI) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `overall` (n=0) | `solver` | +0.0000 [+0.0000, +0.0000] | 0.00% [0.0%, 0.0%] | +0.0000 [+0.0000, +0.0000] | 0.00% | +0.0000 [+0.0000, +0.0000] |
| `overall` (n=0) | `grok_tactics` | +0.0000 [+0.0000, +0.0000] | 0.00% [0.0%, 0.0%] | +0.0000 [+0.0000, +0.0000] | 0.00% | +0.0000 [+0.0000, +0.0000] |
| `overall` (n=0) | `obvious_heuristic` | +0.0000 [+0.0000, +0.0000] | 0.00% [0.0%, 0.0%] | +0.0000 [+0.0000, +0.0000] | 0.00% | +0.0000 [+0.0000, +0.0000] |

## 3. Mole Forge Evolutionary DSL Suite (`mole_forge_suite`)

| Run Folder | Tier | Gens | Valid LLM Children | Best Fitness | Default Dev Fitness | Fresh Solver Acc | Fresh Min Regret | Default Fresh Min Regret | Confirm Holdout Acc | Calls | Cost (USD) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `results/gemini/roles_carbon/adaptive_mole/mole-forge-carbon-easy-deep` | `easy` | 6 | 25 | 0.5613 | 0.3412 | 75.00% | 0.1595 | 0.0600 | 65.00% (n=40) | 34 | $0.0913 |
| `results/gemini/roles_carbon/adaptive_mole/mole-forge-carbon-med-deep` | `medium` | 8 | 43 | 0.7381 | 0.6315 | 85.00% | 0.1390 | 0.1610 | 90.00% (n=40) | 19 | $0.1288 |
| `results/gemini/roles_carbon/adaptive_mole/mole-forge-carbon-hard-deep` | `hard` | 8 | 49 | 0.3745 | 0.0560 | 90.00% | 0.2310 | 0.1650 | 80.00% (n=40) | 8 | $0.2042 |
| `results/gemini/roles_carbon/adaptive_mole/mole-forge-carbon-v14` | `hard` | 3 | 6 | 0.3700 | 0.2450 | 95.00% | 0.2395 | 0.2420 | 90.00% (n=40) | 12 | $0.0275 |

## 4. PAIRED Solvable Scenario Designer Suite (`paired_designer_suite`)

| Run Folder | Tier | Subrole | Kept / Valid | Design/Kept Solver Mean | Design/Kept Heuristic Mean | Holdout Full Solver Mean | Holdout Heuristic Mean | Top Scenario | Calls | Cost (USD) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-easy-s10_14` | `easy` | `paired_skill_designer` | 6/6 | +0.8750 | -1.0000 | +0.7775 | -0.7094 | `patient_frame_rotator` | 1 | $0.0241 |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-easy-s15_19` | `easy` | `paired_skill_designer` | 6/6 | +0.8120 | -1.0000 | +0.7505 | -1.0000 | `canary_cautious_framer` | 1 | $0.0192 |
| `results/gemini/roles_carbon/adaptive_mole/paired-designer-carbon` | `medium` | `paired_designer` | 3/4 | +0.5743 | -1.0000 | +0.5165 | -1.0000 | `pile-on-restricted-peers` | 1 | $0.0218 |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-med-s10_14` | `medium` | `paired_skill_designer` | 6/6 | +0.6888 | -1.0000 | +0.5921 | -1.0000 | `paced_cadence_framer` | 1 | $0.0235 |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-med-s15_19` | `medium` | `paired_skill_designer` | 2/6 | +0.6000 | -1.0000 | +0.5527 | -1.0000 | `canary_wary_scapegoater` | 1 | $0.0224 |
| `results/gemini/roles_carbon/adaptive_mole/paired-solvable-scenarios-carbon` | `medium` | `paired_skill_designer` | 3/4 | +0.7100 | -1.0000 | +0.7220 | -0.8110 | `high_tempo_frame_rotator` | 1 | $0.0176 |
| `results/gemini/roles_carbon/adaptive_mole/paired-designer-carbon-hard` | `hard` | `paired_designer` | 6/6 | +0.6827 | -1.0000 | +0.5070 | -1.0000 | `phased-frame-shift-seeded` | 1 | $0.0271 |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-hard` | `hard` | `paired_skill_designer` | 6/6 | +0.6890 | -1.0000 | +0.6280 | -1.0000 | `rotating_blame_sprinter` | 1 | $0.0233 |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-hard-s10_14` | `hard` | `paired_skill_designer` | 5/6 | +0.6280 | -1.0000 | +0.4970 | -1.0000 | `adaptive_heat_deflector` | 1 | $0.0232 |
| `results/gemini/roles_carbon/adaptive_mole/paired-skill-designer-carbon-hard-s15_19` | `hard` | `paired_skill_designer` | 6/6 | +0.6700 | -1.0000 | +0.5707 | -1.0000 | `scattered_blame_blitz` | 1 | $0.0181 |

## 5. De-Duplicated Totals (`totals`)

| Suite Slice | Verified Folders | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `clash_suite` | 16 | 1471 | 36,341,376 | 60,122 | 568,334 | 33,025,731 | $16.218439 |
| `live_arena_suite` | 0 | 0 | 0 | 0 | 0 | 0 | $0.000000 |
| `mole_forge_suite` | 4 | 73 | 29,433 | 25,603 | 13,694 | 0 | $0.451836 |
| `paired_designer_suite` | 10 | 10 | 16,949 | 13,176 | 5,458 | 0 | $0.220238 |
| **total** | **30** | **1554** | **36,387,758** | **98,901** | **587,486** | **33,025,731** | **$16.890513** |
