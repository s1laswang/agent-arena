# Role 2 Consolidated Suite: Adaptive Gemini Mole (`gemini-4-carbon`)

- Role: `adaptive_mole`
- Target Model ID: `gemini-4-carbon`
- Verified `adaptive_mole` run folders consolidated: `10`
- Total Gemini API calls: `474`
- Total tokens (in / out / thinking / cached): `2,134,742` / `33,697` / `58,760` / `1,618,805`
- Total estimated cost (USD): `$2.118327`
- Provenance note: `carbon-vs-carbon-suite/` intentionally omits `meta.json` so `canary.gemini.provenance` does not double-count tokens or costs.

## 1. Head-to-Head Carbon-vs-Carbon Clash Suite (`clash_suite`)

| Slice | Shards | Episodes | Investigator Acc | Investigator Mean | Solver Acc | Solver Mean | Solvable Rate | Mean Regret | Mole Leaks | Mole Frames | Mole Errors | Combined Tokens (in/out/think) | Inv Cost | Mole Cost | Total Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| `medium` | 1 | 2 | 100.00% | +0.6600 | 100.00% | +0.4000 | 100.00% | -0.2600 | 7 | 1 | 0 | `1,812,239/3,638/30,311` | $0.8215 | $0.0667 | $0.8882 |
| `hard` | 0 | 0 | 0.00% | +0.0000 | 0.00% | +0.0000 | 0.00% | +0.0000 | 0 | 0 | 0 | `0/0/0` | $0.0000 | $0.0000 | $0.0000 |
| `overall` | 1 | 2 | 100.00% | +0.6600 | 100.00% | +0.4000 | 100.00% | -0.2600 | 7 | 1 | 0 | `1,812,239/3,638/30,311` | $0.8215 | $0.0667 | $0.8882 |

### Per-Seed Clash Shards

| Run Folder | Tier | Seed | Commit | Inv Score | Inv Correct | Solver Score | Solver Correct | Solvable | Regret | Leaks | Frames | Errors | Cost (USD) |
| --- | --- | ---: | --- | ---: | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `results/gemini_roles/adaptive_mole/carbon-vs-carbon-seed0` | `medium` | 0 | `3bd1d1e229` | +0.6600 | True | +0.4000 | True | True | -0.2600 | 7 | 1 | 0 | $0.8882 |

## 2. Live Arena Adaptive Mole Suite (`live_arena_suite`)

| Slice | Investigator | Adaptive Mole Mean | Adaptive Mole Acc | Default Mole Mean | Default Mole Acc | Delta Mean (Adaptive - Default) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `medium` (n=6) | `solver` | +0.2833 | 50.00% | +0.5967 | 83.33% | -0.3134 |
| `medium` (n=6) | `grok_tactics` | +0.0000 | 0.00% | +0.4417 | 83.33% | -0.4417 |
| `medium` (n=6) | `obvious_heuristic` | -1.0000 | 0.00% | -1.0000 | 0.00% | +0.0000 |
| `hard` (n=6) | `solver` | +0.4317 | 83.33% | +0.6333 | 100.00% | -0.2016 |
| `hard` (n=6) | `grok_tactics` | +0.0000 | 0.00% | +0.6200 | 100.00% | -0.6200 |
| `hard` (n=6) | `obvious_heuristic` | -1.0000 | 0.00% | -1.0000 | 0.00% | +0.0000 |
| `overall` (n=12) | `solver` | +0.3575 | 66.67% | +0.6150 | 91.67% | -0.2575 |
| `overall` (n=12) | `grok_tactics` | +0.0000 | 0.00% | +0.5308 | 91.67% | -0.5308 |
| `overall` (n=12) | `obvious_heuristic` | -1.0000 | 0.00% | -1.0000 | 0.00% | +0.0000 |

### Live Arena Seed Batches

| Run Folder | Tier | Seeds | Commit | Decisions | Leaks | Frames | LLM Errors | Solvable | Calls | Tokens (in/out/think) | Cost (USD) |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-med012` | `medium` | `[0, 1, 2]` | `d39e88c39e` | 77 | 59 | 77 | 0 | True | 77 | `61,299/4,959/5,588` | $0.2281 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-med345` | `medium` | `[3, 4, 5]` | `c00d49189d` | 86 | 77 | 86 | 0 | True | 86 | `71,969/5,638/6,358` | $0.2639 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-hard012` | `hard` | `[0, 1, 2]` | `03c676c1d3` | 97 | 86 | 97 | 0 | True | 97 | `86,618/6,331/6,287` | $0.2994 |
| `results/gemini_roles/adaptive_mole/arena-live-carbon-hard345` | `hard` | `[3, 4, 5]` | `c00d49189d` | 106 | 88 | 106 | 0 | True | 106 | `92,992/6,876/6,671` | $0.3215 |

## 3. Mole Forge Evolutionary DSL Suite (`mole_forge_suite`)

| Run Folder | Tier | Gens | Valid LLM Children | Best Fitness | Default Dev Fitness | Fresh Solver Acc | Fresh Min Regret | Default Fresh Min Regret | Calls | Cost (USD) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `results/gemini_roles/adaptive_mole/mole-forge-carbon-v14` | `hard` | 3 | 6 | 0.3700 | 0.2450 | 95.00% | 0.2395 | 0.2420 | 12 | $0.0275 |

## 4. PAIRED Solvable Scenario Designer Suite (`paired_designer_suite`)

| Run Folder | Tier | Subrole | Kept / Valid | Design/Kept Solver Mean | Design/Kept Heuristic Mean | Holdout Full Solver Mean | Holdout Heuristic Mean | Top Scenario | Calls | Cost (USD) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `results/gemini_roles/adaptive_mole/paired-designer-carbon` | `medium` | `paired_designer` | 3/4 | +0.5743 | -1.0000 | n/a | n/a | - | 1 | $0.0218 |
| `results/gemini_roles/adaptive_mole/paired-solvable-scenarios-carbon` | `medium` | `paired_skill_designer` | 3/4 | +0.7100 | -1.0000 | +0.7220 | -0.8110 | `high_tempo_frame_rotator` | 1 | $0.0176 |
| `results/gemini_roles/adaptive_mole/paired-designer-carbon-hard` | `hard` | `paired_designer` | 6/6 | +0.6827 | -1.0000 | n/a | n/a | - | 1 | $0.0271 |
| `results/gemini_roles/adaptive_mole/paired-skill-designer-carbon-hard` | `hard` | `paired_skill_designer` | 6/6 | +0.6890 | -1.0000 | +0.6280 | -1.0000 | `rotating_blame_sprinter` | 1 | $0.0233 |

## 5. De-Duplicated Role 2 Totals (`totals`)

| Suite Slice | Verified Folders | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `clash_suite` | 1 | 92 | 1,812,239 | 3,638 | 30,311 | 1,618,805 | $0.888241 |
| `live_arena_suite` | 4 | 366 | 312,878 | 23,804 | 24,904 | 0 | $1.112836 |
| `mole_forge_suite` | 1 | 12 | 2,546 | 1,060 | 1,180 | 0 | $0.027492 |
| `paired_designer_suite` | 4 | 4 | 7,079 | 5,195 | 2,365 | 0 | $0.089758 |
| **total** | **10** | **474** | **2,134,742** | **33,697** | **58,760** | **1,618,805** | **$2.118327** |
