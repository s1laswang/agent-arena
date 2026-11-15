# Role 1 Consolidated Suite: World Text & Persona Synthesis (`gemini-4-carbon`)

- Role: `world_text`
- Target Model ID: `gemini-4-carbon`
- Verified `world_text` run folders consolidated: `15`
- Total Gemini API calls: `1126`
- Total tokens (in / out / thinking / cached): `27,867,443` / `525,975` / `555,696` / `25,362,601`
- Total estimated cost (USD): `$14.751282`
- Non-leak & safety audit: `truth_leaks=0`, `prompt_leaks=0`, `lint_violations=0`, `stego_violations=0`, `fallbacks=0`, `secret_leaks=0` (`all_clean=True`)
- Provenance note: `worldtext-carbon-suite/` intentionally omits `meta.json` so `canary.gemini.provenance` does not double-count tokens or costs.

## 1. Company Personas & Workplace Chatter (`company_personas_suite`)

| Slice | Worlds | Personas | Solver Acc (95% CI) | Solver Mean (95% CI) | Template Mean (95% CI) | Paired Delta (95% CI) |
| --- | ---: | ---: | --- | --- | --- | --- |
| `easy` | 4 | 48 | 100.0% [51.0%, 100.0%] | +0.8000 [+0.7550, +0.8500] | +0.8000 [+0.7550, +0.8500] | +0.0000 [+0.0000, +0.0000] |
| `medium` | 10 | 200 | 90.0% [59.6%, 98.2%] | +0.6660 [+0.4800, +0.7940] | +0.7300 [+0.6350, +0.8000] | -0.0640 [-0.1880, +0.0020] |
| `hard` | 10 | 400 | 100.0% [72.2%, 100.0%] | +0.6340 [+0.5350, +0.7030] | +0.6200 [+0.5210, +0.6910] | +0.0140 [+0.0000, +0.0420] |
| `overall` | 24 | 648 | 95.8% [79.8%, 99.3%] | +0.6750 [+0.5842, +0.7446] | +0.6958 [+0.6367, +0.7467] | -0.0208 [-0.0792, +0.0133] |

## 2. Bias-Flavoured Workplace Chatter & Investigator Ablation (`biased_chatter_suite`)

- Biased chatter corpus: `70` messages (`70` live LLM, `0` fallbacks) across `2` folders
- Paired ablation episodes: `24` across `2` folders

| Slice | Policy | Paired Seeds | Biased Mean (95% CI) | Template Mean (95% CI) | Paired Delta (95% CI) | Biased Acc | Rumor Distraction |
| --- | --- | ---: | --- | --- | --- | ---: | ---: |
| `medium` | `carbon` | 2 | +0.7050 [+0.6500, +0.7600] | +0.6400 [+0.6000, +0.6800] | +0.0650 [+0.0500, +0.0800] | 100.0% | 100.0% |
| `medium` | `solver` | 2 | +0.7650 [+0.6900, +0.8400] | +0.7650 [+0.6900, +0.8400] | +0.0000 [+0.0000, +0.0000] | 100.0% | 0.0% |
| `medium` | `obvious_heuristic` | 2 | -1.0000 [-1.0000, -1.0000] | -1.0000 [-1.0000, -1.0000] | +0.0000 [+0.0000, +0.0000] | 0.0% | 0.0% |
| `hard` | `carbon` | 2 | +0.6200 [+0.5800, +0.6600] | +0.6450 [+0.5400, +0.7500] | -0.0250 [-0.1700, +0.1200] | 100.0% | 100.0% |
| `hard` | `solver` | 2 | +0.6650 [+0.6400, +0.6900] | +0.6650 [+0.6400, +0.6900] | +0.0000 [+0.0000, +0.0000] | 100.0% | 0.0% |
| `hard` | `obvious_heuristic` | 2 | -1.0000 [-1.0000, -1.0000] | -1.0000 [-1.0000, -1.0000] | +0.0000 [+0.0000, +0.0000] | 0.0% | 0.0% |
| `overall` | `carbon` | 4 | +0.6625 [+0.6000, +0.7325] | +0.6425 [+0.5700, +0.7150] | +0.0200 [-0.1075, +0.1025] | 100.0% | 100.0% |
| `overall` | `solver` | 4 | +0.7150 [+0.6525, +0.8025] | +0.7150 [+0.6525, +0.8025] | +0.0000 [+0.0000, +0.0000] | 100.0% | 0.0% |
| `overall` | `obvious_heuristic` | 4 | -1.0000 [-1.0000, -1.0000] | -1.0000 [-1.0000, -1.0000] | +0.0000 [+0.0000, +0.0000] | 0.0% | 0.0% |

## 3. Persona-Conditioned Live Suspect Interviews (`persona_interviews_suite`)

- Worlds / Live interviews: `15` / `120` across `3` folders
- Signal calibration accuracy: `100.0%` [96.9%, 100.0%]
- Counterfactual prompt invariance: `100.0%` [98.9%, 100.0%]
- SolverPolicy parity: `+0.6540` [+0.5513, +0.7400] vs template `+0.6440` [+0.5440, +0.7327] (delta `+0.0100` [+0.0000, +0.0287])

## 4. Dynamic Mid-Episode Corporate Incident Events (`dynamic_events_suite`)

| Slice | Worlds | Live-Events Solver (95% CI) | Baseline Solver (95% CI) | Paired Delta (95% CI) | Solver Acc | ObviousHeuristic |
| --- | ---: | --- | --- | --- | ---: | ---: |
| `medium` | 3 | +0.6933 [+0.6000, +0.7900] | +0.6933 [+0.6000, +0.7900] | +0.0000 [+0.0000, +0.0000] | 100.0% | -1.0000 |
| `hard` | 8 | +0.5988 [+0.4950, +0.6750] | +0.5988 [+0.4950, +0.6750] | +0.0000 [+0.0000, +0.0000] | 100.0% | -1.0000 |
| `overall` | 11 | +0.6245 [+0.5418, +0.6955] | +0.6245 [+0.5418, +0.6955] | +0.0000 [+0.0000, +0.0000] | 100.0% | -1.0000 |

## 5. Thinking-Level World Synthesis Calibration (`thinking_calibration_suite`)

| Thinking Level | Worlds | Thinking Tokens | Think Tok / World | Output Tokens | Distinct Bigrams | Solver Mean | Cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `low` | 2 | 0 | 0.0 | 4,668 | 1,178.0 | +0.7800 | $0.0627 |
| `medium` | 2 | 3,703 | 1,851.5 | 4,307 | 1,124.0 | +0.7800 | $0.0962 |
| `high` | 2 | 38,674 | 19,337.0 | 5,257 | 1,750.0 | +0.7800 | $0.4554 |

## 6. De-Duplicated Role 1 (`world_text`) Totals (`totals`)

| Subrole Slice | Verified Folders | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `biased_chatter` | 1 | 2 | 3,429 | 2,734 | 1,756 | 0 | $0.034198 |
| `biased_chatter_hard` | 1 | 12 | 32,161 | 13,478 | 7,609 | 0 | $0.199102 |
| `biased_chatter_investigator_ablation` | 2 | 806 | 27,351,811 | 400,343 | 352,497 | 25,358,784 | $10.525358 |
| `company_personas_chatter` | 4 | 129 | 170,729 | 74,513 | 99,845 | 0 | $2.085038 |
| `dynamic_mid_episode_events` | 3 | 33 | 166,943 | 11,924 | 19,720 | 3,817 | $0.650326 |
| `persona_interviews` | 3 | 120 | 118,268 | 8,751 | 31,892 | 0 | $0.642966 |
| `thinking_level_calibration` | 1 | 24 | 24,102 | 14,232 | 42,377 | 0 | $0.614294 |
| **total** | **15** | **1126** | **27,867,443** | **525,975** | **555,696** | **25,362,601** | **$14.751282** |
